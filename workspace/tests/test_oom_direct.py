"""OOM 内存炸弹测试脚本。

测试目标：
  1. DockerRunner 直接执行内存炸弹代码，验证 OOM Kill 行为
  2. 宿主机是否不受影响
  3. 错误信息是否被正确捕获

测试环境：USE_DOCKER=true，Docker 容器内存限制 512m。
"""

import os
import sys
import time
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

os.environ["USE_DOCKER"] = "true"

from src.agent.sandbox.docker_runner import DockerRunner


def test_oom_direct():
    """直接测试 DockerRunner 对内存炸弹代码的处理。"""
    workspace = project_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "src").mkdir(parents=True, exist_ok=True)
    (workspace / "output").mkdir(parents=True, exist_ok=True)

    runner = DockerRunner(
        workspace_path=str(workspace),
        memory="512m",
        cpus="1.0",
        pids_limit=64,
        read_only=True,
    )

    # 1 亿个整数的内存炸弹 — Python int ~28 bytes + list pointer ~8 bytes ≈ 36 bytes/element
    # 100M * 36 bytes ≈ 3.6 GB，远超 512m Docker 限制
    code = """
import sys

print("Starting memory bomb test...")
print(f"Python version: {sys.version}")

try:
    n = 100_000_000  # 1 亿个整数
    print(f"Attempting to create a list of {n:,} integers...")
    print(f"Estimated memory: {n * 36 / 1024**3:.1f} GB")

    data = list(range(n))

    print(f"List created successfully with {len(data):,} elements")
    print(f"First: {data[0]}, Last: {data[-1]}")
except MemoryError as e:
    print(f"MemoryError caught in Python: {e}")
except Exception as e:
    print(f"Exception caught in Python: {type(e).__name__}: {e}")

print("Done.")
"""

    print("=" * 60)
    print("OOM 内存炸弹直接测试")
    print("=" * 60)
    print(f"工作区: {workspace}")
    print(f"Docker 镜像: {runner.image}")
    print(f"内存限制: {runner.memory}")
    print(f"CPU 限制: {runner.cpus}")
    print(f"代码: 创建 1 亿个整数的列表 (~3.6 GB)")
    print(f"Docker 内存限制: 512m")
    print("-" * 60)
    print("开始执行...")
    print()

    start_time = time.time()

    result = runner.run(code, timeout=30)

    elapsed = time.time() - start_time

    print()
    print("=" * 60)
    print("测试结果")
    print("=" * 60)
    print(f"耗时: {elapsed:.1f}s")
    print(f"returncode: {result['returncode']}")
    print(f"stdout ({len(result['stdout'])} chars):")
    print(result["stdout"][:1000] if result["stdout"] else "(empty)")
    print()
    print(f"stderr ({len(result['stderr'])} chars):")
    print(result["stderr"][:1000] if result["stderr"] else "(empty)")
    print()
    print(f"file_path: {result.get('file_path', 'N/A')}")

    # 检查容器残留
    print()
    print("-" * 60)
    print("检查 Docker 容器残留...")
    import subprocess
    check = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=dc-sandbox", "--format", "{{.Names}} {{.Status}}"],
        capture_output=True,
        text=True,
    )
    if check.stdout.strip():
        print(f"⚠️ 发现残留容器: {check.stdout.strip()}")
    else:
        print("✅ 无残留容器")

    # 分析结果
    print()
    print("-" * 60)
    print("分析结果")
    print("-" * 60)

    returncode = result["returncode"]
    stderr = (result.get("stderr") or "").lower()
    stdout = (result.get("stdout") or "").lower()
    combined = stderr + stdout

    if returncode != 0:
        print("✅ 返回码非 0（执行失败，符合预期）")

    # Docker OOM Kill 特征：exit code 137 (SIGKILL=9, 128+9=137)
    if "137" in stderr or "oom" in combined or "killed" in combined or "memory" in combined:
        print("✅ 检测到 OOM/Memory 相关错误信息")
    elif returncode == 137 or returncode == -1:
        print("✅ Docker 容器执行失败（OOM Kill 或资源限制触发）")
    else:
        # Check subprocess output for docker error signs
        if returncode == 0 and "list created successfully" in stdout:
            print("⚠️ 代码竟然成功执行了（可能 Docker 内存限制未生效）")
        elif "docker" in stderr:
            print("⚠️ Docker 基础设施错误（非 OOM 相关）")

    # Overall verdict
    if returncode != 0 and ("137" in str(result) or "oom" in combined or "killed" in combined or "memory" in combined or returncode == 137):
        print()
        print("🏆 结论：Docker 容器 OOM Kill 成功，错误信息被正确捕获")
    elif returncode != 0:
        print()
        print("✅ 结论：代码执行失败（符合预期），返回码: {}".format(returncode))
    else:
        print()
        print("⚠️ 结论：代码执行成功（不符合预期 — 应被 OOM Kill）")

    return result


if __name__ == "__main__":
    result = test_oom_direct()
    # Exit with 0 if the test behaved as expected (OOM killed)
    # Exit with 1 if unexpected success (shouldn't happen)
    if result["returncode"] != 0:
        sys.exit(0)
    else:
        sys.exit(1)
