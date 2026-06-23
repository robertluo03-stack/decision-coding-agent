"""loguru 统一日志配置模块。

提供 init_logger() 函数，在 graph.py 编译入口调用，配置：
- debug.log：DEBUG 及以上级别，按天轮转，保留 7 天，旧文件 zip 压缩
- error.log：ERROR 及以上级别，按天轮转，保留 7 天，旧文件 zip 压缩
- get_logger(name)：获取绑定模块名称的 logger，便于各节点记录日志
"""

from pathlib import Path

from loguru import logger as _root_logger


def init_logger() -> None:
    """初始化 loguru 日志配置。

    在项目根目录下的 logs/ 目录创建两个日志文件：
    - debug.log：记录 DEBUG 及以上级别
    - error.log：记录 ERROR 及以上级别
    均按天轮转（每天午夜），保留最近 7 天，旧日志自动 zip 压缩。
    日志格式统一为：{time} | {level} | {name} | {message}

    此函数幂等：如果已有同名 handler 则先移除再重新添加。
    """
    # ---- 计算项目根目录 ----
    # logger_config.py 位于 src/agent/，向上两级即为项目根目录
    project_root = Path(__file__).resolve().parent.parent.parent

    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # ---- 日志格式 ----
    log_format = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}"

    # ---- 移除已有的 handler（确保幂等） ----
    _root_logger.remove()

    # ---- DEBUG 日志：DEBUG 及以上级别 ----
    _root_logger.add(
        logs_dir / "debug.log",
        level="DEBUG",
        format=log_format,
        rotation="00:00",  # 每天午夜轮转
        retention="7 days",  # 保留 7 天
        compression="zip",  # 旧日志 zip 压缩
        encoding="utf-8",
        enqueue=True,  # 线程安全，避免多线程写入冲突
    )

    # ---- ERROR 日志：ERROR 及以上级别 ----
    _root_logger.add(
        logs_dir / "error.log",
        level="ERROR",
        format=log_format,
        rotation="00:00",
        retention="7 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
    )

    _root_logger.info("loguru 日志系统初始化完成，日志目录: {}", logs_dir)


def get_logger(name: str):
    """获取绑定模块名称的 loguru logger。

    通过 logger.bind(name=...) 将 {name} 字段注入日志格式，
    各节点调用时传入自身名称（如 "Planner"、"Coder" 等），
    日志中的 {name} 位置将显示该标识。

    Args:
        name: 模块/节点名称，将出现在日志的 {name} 字段

    Returns:
        绑定了 name 的 loguru logger 实例

    用法:
        from src.agent.logger_config import get_logger
        logger = get_logger("Planner")
        logger.info("进入节点 ...")
    """
    return _root_logger.bind(name=name)
