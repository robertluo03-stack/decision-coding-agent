"""Docker 沙箱执行器 — 在隔离容器中安全执行 Python 代码。

通过 Docker 容器提供比 subprocess 更强的隔离性：
  - 文件系统隔离：宿主机 workspace 只读挂载，防止代码篡改工作区
  - 输出独立：/workspace/output/ 单独可写挂载
  - 网络隔离：容器默认无网络，防止恶意外连
  - 非 root 用户执行：Dockerfile 已配置 appuser
  - 自动清理：执行结束后 --rm 删除容器

路径约定：
  宿主机 {workspace_path}       ←→ 容器内 /workspace (ro)
  宿主机 {workspace_path}/src/  ←→ 容器内 /workspace/src/ (ro)
  宿主机 {workspace_path}/output/ ←→ 容器内 /workspace/output/ (rw)
"""

import subprocess
import uuid
from pathlib import Path

from loguru import logger


class DockerRunner:
    """在 Docker 容器中安全执行 Python 代码。

    使用方式:
        runner = DockerRunner(workspace_path="/path/to/workspace")
        result = runner.run("print('hello')")
        # result = {"stdout": "hello\\n", "stderr": "", "returncode": 0, "file_path": "..."}

    Attributes:
        image: Docker 镜像名称（需预先 docker build）
        workspace_path: 宿主机工作区绝对路径
    """

    # ------------------------------------------------------------------
    # 常量
    # ------------------------------------------------------------------

    _CONTAINER_WORKSPACE: str = "/workspace"
    _CONTAINER_SRC_DIR: str = "/workspace/src"
    _CONTAINER_OUTPUT_DIR: str = "/workspace/output"

    def __init__(
        self,
        workspace_path: str,
        image: str = "decision-coder-sandbox:latest",
    ) -> None:
        """初始化 Docker 执行器。

        Args:
            image: Docker 镜像名，默认 "decision-coder-sandbox:latest"。
                   该镜像需预先通过项目根目录的 Dockerfile 构建：
                     docker build -t decision-coder-sandbox:latest .
            workspace_path: 宿主机工作区绝对路径。
                            代码会写入 {workspace_path}/src/ 子目录。
                            输出会写入 {workspace_path}/output/ 子目录。
        """
        self.image: str = image
        self.workspace_path: Path = Path(workspace_path).resolve()
        logger.debug(
            "[DockerRunner] 初始化 | image={} | workspace={}",
            self.image,
            self.workspace_path,
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
    # 执行入口
    # ------------------------------------------------------------------

    def run(self, code: str, timeout: int = 30) -> dict:
        """在 Docker 容器中执行 Python 代码。

        执行流程：
          1. 将 code 写入宿主机 {workspace_path}/src/temp_{uuid}.py
          2. 使用 docker run --rm --name <uuid> 启动一次性容器：
             - 只读挂载 workspace 用于代码读取
             - 单独可写挂载 /workspace/output 用于输出文件
             - 容器内以非 root 用户 appuser 执行 python /workspace/src/temp_{uuid}.py
          3. 捕获 stdout、stderr、returncode
          4. 超时时强制 docker kill + docker rm 确保不残留容器
          5. 返回结构化执行结果

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

        # ---- 3. 构建 docker run 命令 ----
        # --name:         指定容器名，超时时用于 docker kill 定位
        # --rm:           正常退出时自动删除容器
        # -v ws:/workspace:ro: 只读挂载宿主机 workspace（安全：代码无法篡改工作区）
        # -v ws/output:/workspace/output: 单独可写挂载输出目录
        # --network none: 禁用网络（防止恶意外连 / 数据泄露）
        cmd = [
            "docker", "run", "--rm", "--name", container_name,
            # 文件系统挂载
            "-v", f"{self.workspace_path}:{self._CONTAINER_WORKSPACE}:ro",
            "-v", f"{output_dir}:{self._CONTAINER_OUTPUT_DIR}",
            # 网络隔离
            "--network", "none",
            self.image,
            "python", container_file,
        ]

        logger.debug("[DockerRunner] docker 命令 | cmd={}", " ".join(cmd))

        # ---- 4. 执行 ----
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                # stdin 关闭，防止子进程陷入交互等待
                stdin=subprocess.DEVNULL,
            )

            logger.info(
                "[DockerRunner] 执行完成 | returncode={} | stdout_len={} | stderr_len={}",
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
