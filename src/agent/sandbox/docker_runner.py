"""Docker 沙箱执行器 — 在隔离容器中安全执行 Python 代码。

通过 Docker 容器提供比 subprocess 更强的隔离性：
  - 文件系统隔离：宿主机 workspace 只读挂载，防止代码篡改工作区
  - 输出独立：/workspace/output/ 单独可写挂载
  - 网络隔离：容器默认无网络，防止恶意外连
  - 非 root 用户执行：Dockerfile 已配置 appuser
  - 资源限制：内存 512m / CPU 1 核 / 进程数 64 / 根文件系统只读
  - 自动清理：执行结束后 --rm 删除容器

路径约定：
  宿主机 {workspace_path}       ←→ 容器内 /workspace (ro)
  宿主机 {workspace_path}/src/  ←→ 容器内 /workspace/src/ (ro)
  宿主机 {workspace_path}/output/ ←→ 容器内 /workspace/output/ (rw)
"""

import shlex
import subprocess
import uuid
from pathlib import Path

from loguru import logger

from src.agent.sandbox.security_checker import check_code_safety


class DockerRunner:
    """在 Docker 容器中安全执行 Python 代码。

    使用方式:
        runner = DockerRunner(workspace_path="/path/to/workspace")
        result = runner.run("print('hello')")
        # result = {"stdout": "hello\\n", "stderr": "", "returncode": 0, "file_path": "..."}

    资源限制（可通过构造参数调整）:
        memory:    容器最大内存，默认 "512m"
        cpus:      容器最大 CPU 核数，默认 "1.0"
        pids_limit: 容器最大进程数，默认 64
        read_only:  根文件系统只读（volume/tmpfs 除外），默认 True

    Attributes:
        image: Docker 镜像名称（需预先 docker build）
        workspace_path: 宿主机工作区绝对路径
        memory: 内存限制
        cpus: CPU 限制
        pids_limit: PID 数量限制
        read_only: 是否启用根文件系统只读
    """

    # ------------------------------------------------------------------
    # 常量
    # ------------------------------------------------------------------

    _CONTAINER_WORKSPACE: str = "/workspace"
    _CONTAINER_SRC_DIR: str = "/workspace/src"
    _CONTAINER_OUTPUT_DIR: str = "/workspace/output"

    # Docker daemon 不支持某些 flag 时的错误关键词（用于 graceful fallback）
    _UNSUPPORTED_FLAG_PATTERNS: tuple[str, ...] = (
        "unknown flag",
        "is not supported",
        "flag provided but not defined",
        "unknown flag: --pids-limit",
    )

    def __init__(
        self,
        workspace_path: str,
        image: str = "decision-coder-sandbox:latest",
        memory: str = "512m",
        cpus: str = "1.0",
        pids_limit: int = 64,
        read_only: bool = True,
    ) -> None:
        """初始化 Docker 执行器。

        Args:
            workspace_path: 宿主机工作区绝对路径。
                            代码会写入 {workspace_path}/src/ 子目录。
                            输出会写入 {workspace_path}/output/ 子目录。
            image: Docker 镜像名，默认 "decision-coder-sandbox:latest"。
                   该镜像需预先通过项目根目录的 Dockerfile 构建：
                     docker build -t decision-coder-sandbox:latest .
            memory: 容器最大内存限制，默认 "512m"。
                    Docker --memory 参数格式（如 "256m", "1g"）。
            cpus: 容器最大 CPU 核数限制，默认 "1.0"。
                  Docker --cpus 参数格式（如 "0.5", "2.0"）。
            pids_limit: 容器内最大进程数，默认 64。
                        Docker --pids-limit 参数。
                        设为 0 表示不限制（禁用 flag）。
            read_only: 根文件系统只读，默认 True。
                       启用后 /tmp 自动以 tmpfs 挂载以保障 Python 正常运行。
                       可通过 workspace/output volume 写入输出文件。
        """
        self.image: str = image
        self.workspace_path: Path = Path(workspace_path).resolve()
        self.memory: str = memory
        self.cpus: str = cpus
        self.pids_limit: int = pids_limit
        self.read_only: bool = read_only
        logger.debug(
            "[DockerRunner] 初始化 | image={} | workspace={} | "
            "memory={} | cpus={} | pids_limit={} | read_only={}",
            self.image,
            self.workspace_path,
            self.memory,
            self.cpus,
            self.pids_limit,
            self.read_only,
        )

    # ------------------------------------------------------------------
    # 路径转换
    # ------------------------------------------------------------------

    def _to_container_path(self, host_path: Path) -> str:
        """将宿主机路径转换为容器内路径。

        核心逻辑：
          宿主机 {workspace_path}/xxx  → 容器内 /workspace/xxx

        Args:
            host_path: 宿主机上的绝对路径

        Returns:
            容器内的绝对路径字符串

        Raises:
            ValueError: host_path 不在 workspace_path 子目录下
        """
        host_resolved = host_path.resolve()
        try:
            relative = host_resolved.relative_to(self.workspace_path)
        except ValueError:
            raise ValueError(
                f"路径 {host_path} 不在工作区 {self.workspace_path} 下，无法转换为容器路径"
            )
        return f"{self._CONTAINER_WORKSPACE}/{relative.as_posix()}"

    def _to_host_path(self, container_path: str) -> Path:
        """将容器内路径转换为宿主机路径。

        核心逻辑：
          容器内 /workspace/xxx → 宿主机 {workspace_path}/xxx

        Args:
            container_path: 容器内的绝对路径

        Returns:
            宿主机上的绝对 Path

        Raises:
            ValueError: container_path 不以 /workspace/ 开头
        """
        prefix = self._CONTAINER_WORKSPACE + "/"
        if not container_path.startswith(prefix):
            raise ValueError(
                f"容器路径 {container_path} 不以 {self._CONTAINER_WORKSPACE}/ 开头，无法转换"
            )
        relative = container_path[len(prefix):]
        return self.workspace_path / relative

    # ------------------------------------------------------------------
    # 容器清理
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup_container(container_name: str) -> None:
        """超时后强制终止并删除容器，确保不残留。

        先 docker kill（发送 SIGKILL 立即终止进程），
        再 docker rm（删除容器资源）。

        所有异常静默吞掉 — 容器可能已自然退出并被 --rm 清理，
        此时 kill/rm 会报错，属正常情况。

        Args:
            container_name: 容器名称（--name 参数指定）
        """
        # Step 1: force kill — immediately terminates the container process
        try:
            subprocess.run(
                ["docker", "kill", container_name],
                capture_output=True,
                text=True,
                timeout=10,  # kill 本身不应耗时，10s 足够
                stdin=subprocess.DEVNULL,
            )
            logger.debug("[DockerRunner] docker kill {} 完成", container_name)
        except Exception:
            # Container may have already exited or been removed by --rm
            logger.debug("[DockerRunner] docker kill {} 跳过（容器可能已退出）", container_name)

        # Step 2: remove — deletes container resources from disk
        try:
            subprocess.run(
                ["docker", "rm", container_name],
                capture_output=True,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            )
            logger.debug("[DockerRunner] docker rm {} 完成", container_name)
        except Exception:
            # Container may have already been cleaned up
            logger.debug("[DockerRunner] docker rm {} 跳过（容器可能已清理）", container_name)

    # ------------------------------------------------------------------
    # Docker 命令构建
    # ------------------------------------------------------------------

    def _build_docker_cmd(
        self,
        container_name: str,
        container_file: str,
        output_dir: Path,
        *,
        include_all_flags: bool = True,
    ) -> list[str]:
        """构建完整的 docker run 命令。

        分层设计 — 资源限制 flag 可通过 include_all_flags 开关控制：
          - True:  包含所有资源限制（--memory, --cpus, --pids-limit, --read-only）
          - False: 仅包含基础 flag（文件挂载 + 网络隔离），用于 graceful fallback

        Args:
            container_name: 容器名（--name）
            container_file: 容器内 Python 文件路径
            output_dir: 宿主机 output 目录 Path
            include_all_flags: 是否包含全部资源限制 flag

        Returns:
            docker run 命令的 argv 列表
        """
        cmd: list[str] = [
            "docker", "run", "--rm", "--name", container_name,
            # ---- 文件系统挂载 ----
            "-v", f"{self.workspace_path}:{self._CONTAINER_WORKSPACE}:ro",
            "-v", f"{output_dir}:{self._CONTAINER_OUTPUT_DIR}",
        ]

        # ---- 资源限制 ----
        if include_all_flags:
            cmd.extend(["--memory", self.memory])
            cmd.extend(["--cpus", self.cpus])
            if self.pids_limit > 0:
                cmd.extend(["--pids-limit", str(self.pids_limit)])

        # ---- 根文件系统只读 ----
        if include_all_flags and self.read_only:
            cmd.append("--read-only")
            # Python 需要可写的 /tmp 用于临时文件，否则 import/_pyio 会失败
            # :exec 允许在 tmpfs 上执行，某些 Python 操作需要（如 subprocess/cache）
            cmd.extend(["--tmpfs", "/tmp:exec,size=128m"])

        # ---- 网络隔离 ----
        cmd.extend(["--network", "none"])

        # ---- 镜像 + 执行命令 ----
        cmd.extend([self.image, "python", container_file])

        return cmd

    # ------------------------------------------------------------------
    # Graceful fallback 执行
    # ------------------------------------------------------------------

    def _is_flag_error(self, stderr: str) -> bool:
        """检查 Docker stderr 是否包含不支持的 flag 错误。

        不同 Docker 版本 / 环境的报错信息不同：
          - "unknown flag: --pids-limit"
          - "Error: unknown flag"
          - "... is not supported"

        Args:
            stderr: Docker 命令的 stderr 输出

        Returns:
            如果是 flag 不支持的错误返回 True
        """
        stderr_lower = stderr.lower()
        return any(pat in stderr_lower for pat in self._UNSUPPORTED_FLAG_PATTERNS)

    def _execute_docker(
        self,
        container_name: str,
        container_file: str,
        output_dir: Path,
        host_file: Path,
        timeout: int,
    ) -> dict:
        """执行 docker run，带 graceful fallback。

        策略：
          1. 首次尝试：全部资源限制 flag
          2. 若 Docker 报 "unknown flag" 错误 → 回退为最小 flag 集（仅挂载 + 网络隔离）
          3. 超时 / 基础设施异常一视同仁，走统一错误返回

        Args:
            container_name: 容器名
            container_file: 容器内 Python 文件路径
            output_dir: 宿主机 output 目录
            host_file: 宿主机临时文件 Path（用于返回 file_path）
            timeout: 执行超时秒数

        Returns:
            {"stdout": str, "stderr": str, "returncode": int, "file_path": str}
        """
        # 按序尝试的 flag 级别列表
        flag_levels: list[tuple[str, bool]] = [
            ("full", True),      # 全部资源限制
            ("minimal", False),  # 最小 flag 集（兜底）
        ]

        last_result: dict | None = None

        for level_name, include_all in flag_levels:
            cmd = self._build_docker_cmd(
                container_name,
                container_file,
                output_dir,
                include_all_flags=include_all,
            )

            if level_name == "full":
                logger.debug("[DockerRunner] docker 命令 (full) | cmd={}", shlex.join(cmd))
            else:
                logger.warning(
                    "[DockerRunner] 回退到 minimal flag 集 | 上一轮错误: {}",
                    (last_result or {}).get("stderr", "")[:120],
                )

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    stdin=subprocess.DEVNULL,
                )

                # 成功或正常执行错误 → 直接返回
                if result.returncode == 0 or not self._is_flag_error(result.stderr or ""):
                    logger.info(
                        "[DockerRunner] 执行完成 ({}) | returncode={} | stdout_len={} | stderr_len={}",
                        level_name,
                        result.returncode,
                        len(result.stdout or ""),
                        len(result.stderr or ""),
                    )
                    return {
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "returncode": result.returncode,
                        "file_path": str(host_file),
                    }

                # Docker flag 不支持的错误 → 记录并进入下一轮回退
                logger.warning(
                    "[DockerRunner] Docker flag 不支持 ({}) | stderr={}",
                    level_name,
                    (result.stderr or "").strip()[:200],
                )
                last_result = {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                    "file_path": str(host_file),
                }

            except subprocess.TimeoutExpired:
                # 超时不回退 — 直接进入清理流程
                raise  # 由外层 run() 的 TimeoutExpired handler 统一处理

        # 所有级别都失败 → 返回最后的错误
        if last_result is None:
            last_result = {
                "stdout": "",
                "stderr": "Docker 执行失败（所有 flag 级别均不可用）",
                "returncode": -1,
                "file_path": str(host_file),
            }
        return last_result

    # ------------------------------------------------------------------
    # 执行入口
    # ------------------------------------------------------------------

    def run(self, code: str, timeout: int = 30) -> dict:
        """在 Docker 容器中执行 Python 代码。

        执行流程：
          1. 将 code 写入宿主机 {workspace_path}/src/temp_{uuid}.py
          2. 使用 docker run --rm --name <uuid> 启动一次性容器：
             - 内存限制 512m / CPU 限制 1 核 / 进程数限制 64
             - 根文件系统只读（--read-only），/tmp 以 tmpfs 挂载
             - 只读挂载 workspace 用于代码读取
             - 单独可写挂载 /workspace/output 用于输出文件
             - 容器内以非 root 用户 appuser 执行 python /workspace/src/temp_{uuid}.py
          3. 若 Docker 环境不支持某些 flag（如 --pids-limit），自动回退到最小 flag 集
          4. 捕获 stdout、stderr、returncode
          5. 超时时强制 docker kill + docker rm 确保不残留容器
          6. 返回结构化执行结果

        Args:
            code: 待执行的 Python 源代码
            timeout: 执行超时时间（秒），默认 30

        Returns:
            {
                "stdout": str,       # 标准输出
                "stderr": str,       # 标准错误（超时时包含 "[TIMEOUT]" 标识）
                "returncode": int,   # 退出码（0=成功，-1=超时/基础设施错误）
                "file_path": str,    # 宿主机上临时文件的绝对路径
            }
        """
        # ---- 0. 第二道安全防线：AST 语法级危险代码检查 ----
        # Coder 的 _has_dangerous_code() 是第一道防线，此处是兜底。
        # 即使 Coder 漏掉变形写法（如 __import__('os').system('...')），
        # DockerRunner 也能在落地执行前拦截。
        is_safe, reason = check_code_safety(code)
        if not is_safe:
            logger.warning(
                "[DockerRunner] 第二道防线拦截危险代码 | reason={}", reason
            )
            return {
                "stdout": "",
                "stderr": f"Security: Dangerous code blocked by DockerRunner — {reason}",
                "returncode": -1,
                "file_path": "",
            }

        # ---- 1. 准备宿主机目录 ----
        src_dir = self.workspace_path / "src"
        output_dir = self.workspace_path / "output"
        try:
            src_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            error_msg = f"创建工作区目录失败: {exc}"
            logger.error("[DockerRunner] {}", error_msg)
            return {
                "stdout": "",
                "stderr": error_msg,
                "returncode": -1,
                "file_path": "",
            }

        # ---- 2. 写入临时文件 ----
        file_name = f"temp_{uuid.uuid4().hex}.py"
        host_file = src_dir / file_name
        try:
            host_file.write_text(code, encoding="utf-8")
        except OSError as exc:
            error_msg = f"写入临时文件失败: {exc}"
            logger.error("[DockerRunner] {}", error_msg)
            return {
                "stdout": "",
                "stderr": error_msg,
                "returncode": -1,
                "file_path": "",
            }

        container_file = f"{self._CONTAINER_SRC_DIR}/{file_name}"

        # 生成唯一容器名，用于超时时精确 kill
        container_name = f"dc-sandbox-{uuid.uuid4().hex[:12]}"

        logger.info(
            "[DockerRunner] 执行准备完成 | host_file={} | container={} | code_len={}",
            host_file,
            container_name,
            len(code),
        )

        # ---- 3. 执行（带 graceful fallback） ----
        try:
            return self._execute_docker(
                container_name=container_name,
                container_file=container_file,
                output_dir=output_dir,
                host_file=host_file,
                timeout=timeout,
            )

        except subprocess.TimeoutExpired:
            # ---- 超时处理：强制 kill + rm，确保不残留容器 ----
            # subprocess.run 超时后会终止 docker CLI 进程，但容器仍会继续运行。
            # --rm 仅在容器正常退出时清理，超时场景无效，必须手动清理。
            logger.warning(
                "[DockerRunner] 执行超时（{}s）| container={} | 开始强制清理",
                timeout,
                container_name,
            )

            self._cleanup_container(container_name)

            # 二次确认：防止极端情况下清理失败导致残留
            try:
                check = subprocess.run(
                    ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.ID}}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    stdin=subprocess.DEVNULL,
                )
                if check.stdout.strip():
                    logger.warning(
                        "[DockerRunner] 容器仍存在，尝试 docker rm -f | id={}",
                        check.stdout.strip(),
                    )
                    subprocess.run(
                        ["docker", "rm", "-f", container_name],
                        capture_output=True,
                        timeout=10,
                        stdin=subprocess.DEVNULL,
                    )
            except Exception:
                pass  # 二次清理失败不再重试

            error_msg = f"[TIMEOUT] 容器执行超时（{timeout}s），已强制终止并清理容器 {container_name}"
            logger.info("[DockerRunner] {}", error_msg)
            return {
                "stdout": "",
                "stderr": error_msg,
                "returncode": -1,
                "file_path": str(host_file),
            }

        except FileNotFoundError:
            error_msg = "Docker 未安装或未在 PATH 中。请安装 Docker Desktop 或 Docker Engine，并确保 docker 命令可用。"
            logger.error("[DockerRunner] {}", error_msg)
            return {
                "stdout": "",
                "stderr": error_msg,
                "returncode": -1,
                "file_path": str(host_file),
            }

        except Exception as exc:
            error_msg = f"Docker 执行异常: {type(exc).__name__}: {exc}"
            logger.error("[DockerRunner] {}", error_msg)
            return {
                "stdout": "",
                "stderr": error_msg,
                "returncode": -1,
                "file_path": str(host_file),
            }
