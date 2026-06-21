"""文件读写工具 — 基于 MCP 协议。

支持 CSV、Excel、JSON 等格式的读写操作。
"""

import csv
import json
from pathlib import Path
from typing import Optional

from loguru import logger

# 允许的文件扩展名白名单
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json", ".txt", ".md", ".log"}

# 文件大小上限 (10 MB)
MAX_FILE_SIZE = 10 * 1024 * 1024


def read_file(filepath: str, fmt: Optional[str] = None) -> str:
    """读取文件内容，自动推断格式。

    Args:
        filepath: 文件路径
        fmt: 强制指定格式 ("csv" | "json" | "txt")

    Returns:
        文件内容字符串
    """
    path = Path(filepath)
    _validate_file(path)

    fmt = fmt or path.suffix.lstrip(".").lower()

    if fmt == "csv":
        return _read_csv(path)
    elif fmt == "json":
        return _read_json(path)
    else:
        return path.read_text(encoding="utf-8")


def write_file(filepath: str, content: str) -> None:
    """写入文件，自动创建父目录。

    Args:
        filepath: 文件路径
        content: 文件内容
    """
    path = Path(filepath)
    _check_extension(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info(f"File written: {path}")


def read_csv(filepath: str) -> list[dict]:
    """读取 CSV 文件，返回字典列表。"""
    path = Path(filepath)
    _validate_file(path)
    rows = []
    with path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    logger.info(f"CSV read: {len(rows)} rows from {path}")
    return rows


def _read_csv(path: Path) -> str:
    rows = read_csv(str(path))
    return json.dumps(rows, ensure_ascii=False, indent=2)


def _read_json(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(data, ensure_ascii=False, indent=2)


def _validate_file(path: Path) -> None:
    """验证文件存在性、扩展名和大小。"""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    _check_extension(path)
    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"File too large: {path} ({path.stat().st_size} bytes)")


def _check_extension(path: Path) -> None:
    """检查文件扩展名是否在白名单内。"""
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File extension not allowed: {ext}. Allowed: {ALLOWED_EXTENSIONS}")
