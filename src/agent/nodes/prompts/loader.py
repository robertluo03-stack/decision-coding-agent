"""Prompt loader: reads .md files from the prompts directory."""

from pathlib import Path
from functools import lru_cache

_PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=16)
def load_prompt(filename: str) -> str:
    """Load a prompt template from a .md file.

    Args:
        filename: Name of the .md file (e.g. "planner.md")

    Returns:
        The file contents as a string, with leading/trailing whitespace stripped.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    filepath = _PROMPTS_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Prompt file not found: {filepath}")
    return filepath.read_text(encoding="utf-8").strip()
