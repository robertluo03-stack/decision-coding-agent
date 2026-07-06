"""文件读写工具 — 基于 MCP 协议。

支持 CSV、Excel、JSON 等格式的读写操作。
Week 2 版本：路径安全校验 + CallToolResult 包装 + 新增 list_dir / file_exists。
Week 3 Day 1：新增 file_read_csv（pandas 增强） + file_read_excel + 类型推断。
"""

import csv
import json
import os
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

from src.mcp.tools.data_utils import compute_missing_summary, enhance_dtypes

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 允许的文件扩展名白名单
ALLOWED_EXTENSIONS = frozenset({".csv", ".xlsx", ".xls", ".json", ".txt", ".md", ".log"})

# 文件大小上限 (10 MB)
MAX_FILE_SIZE = 10 * 1024 * 1024

# ---------------------------------------------------------------------------
# 工作区路径解析
# ---------------------------------------------------------------------------


def _get_workspace() -> Path:
    """获取工作区根目录（绝对路径）。

    从环境变量 WORKSPACE_PATH 读取，默认 "./workspace" 并 resolve 为绝对路径。
    """
    raw = os.environ.get("WORKSPACE_PATH", "./workspace")
    return Path(raw).resolve()


# ---------------------------------------------------------------------------
# 路径安全校验
# ---------------------------------------------------------------------------


def _resolve_safe_path(filepath: str | Path, workspace: Path | None = None) -> Path:
    """将 filepath 安全解析到 workspace 下的绝对路径。

    规则：
      1. 相对路径以 workspace 为基准拼接
      2. 绝对路径直接 resolve
      3. resolve 后检查是否在 workspace 子树内（禁止 .. 穿越）
      4. 拒绝符号链接逃逸（resolve 展开所有 symlink）

    Args:
        filepath: 用户传入的文件路径（相对或绝对）
        workspace: 工作区根目录，默认从环境变量获取

    Returns:
        workspace 内解析后的绝对 Path

    Raises:
        ValueError: 路径逃逸 workspace 或包含 ".." 穿越
    """
    if workspace is None:
        workspace = _get_workspace()

    ws = workspace.resolve()
    p = Path(filepath)

    # 拒绝包含 ".." 成分的路径（白名单式拦截，避免绕过）
    if ".." in p.parts:
        raise ValueError(f"路径包含 '..' 穿越，已被拦截: {filepath!r}")

    # 相对路径以 workspace 为基准
    if not p.is_absolute():
        p = ws / p

    # resolve 展开所有符号链接和相对成分
    resolved = p.resolve()

    # 检查是否在 workspace 子树内
    try:
        resolved.relative_to(ws)
    except ValueError:
        raise ValueError(
            f"路径不在工作区范围内，已被拦截: {filepath!r} → {resolved}"
        )

    return resolved


# ---------------------------------------------------------------------------
# 扩展名与参数校验
# ---------------------------------------------------------------------------


def _check_extension(path: Path) -> None:
    """检查文件扩展名是否在白名单内。

    无后缀时跳过检查（由上层 read_file 根据 fmt 参数决定是否拒绝）。
    """
    ext = path.suffix.lower()
    if not ext:
        # 无后缀：不做扩展名检查，交由上层 read_file 根据 fmt 参数处理
        return
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"文件扩展名不在白名单: {ext}。允许: {sorted(ALLOWED_EXTENSIONS)}"
        )


def _validate_file(path: Path) -> None:
    """验证文件存在性、扩展名和大小。"""
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    _check_extension(path)
    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"文件过大: {path} ({path.stat().st_size} bytes)")


def _validate_not_binary(path: Path) -> None:
    """检查文件是否为文本格式（简单启发式）。

    读取前 1024 字节，检测 null 字节。不保证 100% 准确，但能拦截典型二进制。
    """
    with path.open("rb") as f:
        chunk = f.read(1024)
    if b"\x00" in chunk:
        raise ValueError(f"文件疑似二进制格式，拒绝读取: {path}")


# ---------------------------------------------------------------------------
# 公开工具函数
# ---------------------------------------------------------------------------


def read_file(
    filepath: str,
    fmt: Optional[str] = None,
    *,
    workspace: str | None = None,
) -> str:
    """读取文件内容，自动推断格式。

    Args:
        filepath: 文件路径（相对 workspace 或绝对路径）
        fmt: 强制指定格式 ("csv" | "json" | "txt")，为空则根据文件后缀自动推断
        workspace: 工作区根目录（默认从环境变量 WORKSPACE_PATH 读取）

    Returns:
        文件内容字符串（CSV/JSON 会格式化为缩进后的 JSON 文本）

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 路径不合法 / 扩展名不允许 / 文件过大 / 疑似二进制
    """
    ws = Path(workspace).resolve() if workspace else _get_workspace()
    path = _resolve_safe_path(filepath, ws)
    _validate_file(path)

    # 确定格式：优先显式 fmt，其次从后缀推断
    fmt = fmt or path.suffix.lstrip(".").lower()

    # 修复：无后缀且未指定 fmt 时，拒绝读取（避免读到二进制文件）
    if not fmt:
        raise ValueError(
            f"无法推断文件格式（无后缀且未指定 fmt 参数）: {filepath!r}。"
            f"请显式指定 fmt=\"txt\"（纯文本）/ fmt=\"csv\" / fmt=\"json\""
        )

    if fmt == "csv":
        return _read_csv(path)
    elif fmt == "json":
        return _read_json(path)
    else:
        # txt / md / log / 其他纯文本：先验证非二进制再读取
        _validate_not_binary(path)
        return path.read_text(encoding="utf-8")


def write_file(
    filepath: str,
    content: str,
    *,
    overwrite: bool = True,
    workspace: str | None = None,
) -> str:
    """写入文件，自动创建父目录。

    Args:
        filepath: 文件路径（相对 workspace 或绝对路径）
        content: 文件内容
        overwrite: 是否允许覆盖已有文件（默认 True；False 时文件已存在则报错）
        workspace: 工作区根目录（默认从环境变量 WORKSPACE_PATH 读取）

    Returns:
        确认消息字符串
    """
    ws = Path(workspace).resolve() if workspace else _get_workspace()
    path = _resolve_safe_path(filepath, ws)
    _check_extension(path)

    # 覆盖保护
    if not overwrite and path.exists():
        raise FileExistsError(
            f"文件已存在且 overwrite=False，拒绝覆盖: {path}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("File written: {}", path)
    return f"OK: 已写入 {path}"


def read_csv(filepath: str, *, workspace: str | None = None) -> str:
    """读取 CSV 文件，返回 JSON 字符串。

    列名从 CSV header 读取，每行映射为一个 JSON 对象。

    Args:
        filepath: CSV 文件路径
        workspace: 工作区根目录

    Returns:
        JSON 字符串，格式: [{"col1": "val1", ...}, ...]
    """
    ws = Path(workspace).resolve() if workspace else _get_workspace()
    path = _resolve_safe_path(filepath, ws)
    _validate_file(path)
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    logger.info("CSV read: {} rows from {}", len(rows), path)
    return json.dumps(rows, ensure_ascii=False, indent=2)


def file_read_csv(
    file_path: str,
    preview_rows: int = 5,
    *,
    workspace: str | None = None,
) -> str:
    """使用 pandas 读取 CSV 文件，返回结构化 JSON（含列信息、类型推断、预览、缺失值）。

    相比 read_csv()（返回纯字符串列表），本函数返回增强的结构化摘要：
      - columns: 列名列表
      - dtypes: 增强类型推断结果（int/float/str/datetime/percentage/mixed）
      - preview: 前 preview_rows 行的字典列表
      - shape: [行数, 列数]
      - missing_summary: 每列缺失值数量（仅包含有缺失的列）

    Args:
        file_path: CSV 文件路径（相对 workspace 或绝对路径）
        preview_rows: 预览行数（默认 5，防止大文件内存溢出）
        workspace: 工作区根目录

    Returns:
        JSON 字符串，包含结构化摘要信息
    """
    ws = Path(workspace).resolve() if workspace else _get_workspace()
    path = _resolve_safe_path(file_path, ws)
    _validate_file(path)

    df = pd.read_csv(path)
    df = df.infer_objects()

    # 限制预览行数
    preview = df.head(preview_rows).to_dict("records")

    result = {
        "columns": list(df.columns),
        "dtypes": enhance_dtypes(df),
        "preview": preview,
        "shape": [len(df), len(df.columns)],
        "missing_summary": compute_missing_summary(df),
    }

    logger.info(
        "file_read_csv: {} | rows={} cols={} | dtypes={} | missing={}",
        path.name,
        len(df),
        len(df.columns),
        len(result["dtypes"]),
        len(result["missing_summary"]),
    )
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


def file_read_excel(
    file_path: str,
    sheet_name: str | int = 0,
    preview_rows: int = 5,
    *,
    workspace: str | None = None,
) -> str:
    """使用 pandas 读取 Excel 文件，返回结构化 JSON。

    返回格式与 file_read_csv() 一致，包含 columns / dtypes / preview / shape / missing_summary。

    Args:
        file_path: Excel 文件路径（.xlsx / .xls，相对 workspace 或绝对路径）
        sheet_name: sheet 名称或索引（默认 0，即第一个 sheet）
        preview_rows: 预览行数（默认 5，防止大文件内存溢出）
        workspace: 工作区根目录

    Returns:
        JSON 字符串，包含结构化摘要信息

    Raises:
        ValueError: sheet_name 不存在时，列出可用的 sheet 名称
    """
    ws = Path(workspace).resolve() if workspace else _get_workspace()
    path = _resolve_safe_path(file_path, ws)
    _validate_file(path)

    # 先检查可用 sheet，以便给出清晰错误信息
    available_sheets = None
    xl = None
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
        available_sheets = xl.sheet_names
    except Exception:
        # 回退：让 pandas 直接读取（可能 engine 不匹配）
        pass

    try:
        if available_sheets is not None:
            if isinstance(sheet_name, int):
                if sheet_name < 0 or sheet_name >= len(available_sheets):
                    raise ValueError(
                        f"Sheet 索引 {sheet_name} 不存在。"
                        f"可用 sheet（共 {len(available_sheets)} 个）: {available_sheets}"
                    )
            else:
                if sheet_name not in available_sheets:
                    raise ValueError(
                        f"Sheet '{sheet_name}' 不存在。"
                        f"可用 sheet: {available_sheets}"
                    )

        df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    finally:
        if xl is not None:
            xl.close()
    df = df.infer_objects()

    # 限制预览行数
    preview = df.head(preview_rows).to_dict("records")

    result = {
        "columns": list(df.columns),
        "dtypes": enhance_dtypes(df),
        "preview": preview,
        "shape": [len(df), len(df.columns)],
        "missing_summary": compute_missing_summary(df),
    }

    # 记录实际使用的 sheet 名称
    actual_sheet = available_sheets[sheet_name] if (available_sheets and isinstance(sheet_name, int)) else sheet_name

    logger.info(
        "file_read_excel: {} | sheet={} | rows={} cols={} | dtypes={} | missing={}",
        path.name,
        actual_sheet,
        len(df),
        len(df.columns),
        len(result["dtypes"]),
        len(result["missing_summary"]),
    )
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


def list_dir(
    dirpath: str = ".",
    *,
    workspace: str | None = None,
) -> str:
    """列出目录内容，返回文件/子目录清单。

    Args:
        dirpath: 目录路径（相对 workspace，默认 "."）
        workspace: 工作区根目录

    Returns:
        JSON 字符串，格式: {
            "dir": "<绝对路径>",
            "entries": [
                {"name": "...", "type": "file"|"dir", "size": <bytes>},
                ...
            ]
        }
    """
    ws = Path(workspace).resolve() if workspace else _get_workspace()
    path = _resolve_safe_path(dirpath, ws)

    if not path.exists():
        raise FileNotFoundError(f"目录不存在: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"不是目录: {path}")

    entries: list[dict] = []
    for entry in sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        try:
            size = entry.stat().st_size if entry.is_file() else 0
        except OSError:
            size = 0
        entries.append({
            "name": entry.name,
            "type": "dir" if entry.is_dir() else "file",
            "size": size,
        })

    result = {"dir": str(path), "entries": entries}
    logger.info("list_dir: {} entries in {}", len(entries), path)
    return json.dumps(result, ensure_ascii=False, indent=2)


def file_exists(
    filepath: str,
    *,
    workspace: str | None = None,
) -> str:
    """检查文件是否存在。

    Args:
        filepath: 文件路径（相对 workspace 或绝对路径）
        workspace: 工作区根目录

    Returns:
        JSON 字符串，格式: {"exists": true|false, "filepath": "<绝对路径>"}
    """
    ws = Path(workspace).resolve() if workspace else _get_workspace()

    # 尝试解析路径，即使路径不存在也可以做安全检查
    # 但 resolve_safe_path 需要路径存在才能 resolve...
    # 这里我们做轻量安全检查：拒绝 .. 穿越，然后拼接
    if ".." in Path(filepath).parts:
        raise ValueError(f"路径包含 '..' 穿越，已被拦截: {filepath!r}")

    p = Path(filepath)
    if not p.is_absolute():
        p = ws / p

    resolved = p.resolve()

    # 检查是否在 workspace 子树内
    try:
        resolved.relative_to(ws)
    except ValueError:
        raise ValueError(
            f"路径不在工作区范围内，已被拦截: {filepath!r} → {resolved}"
        )

    exists = resolved.exists()
    result = {"exists": exists, "filepath": str(resolved)}
    logger.info("file_exists: {} → {}", filepath, exists)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _read_csv(path: Path) -> str:
    """CSV → JSON 字符串。"""
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    logger.info("CSV read (internal): {} rows from {}", len(rows), path)
    return json.dumps(rows, ensure_ascii=False, indent=2)


def _read_json(path: Path) -> str:
    """读取 JSON 文件并重新格式化输出。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(data, ensure_ascii=False, indent=2)
