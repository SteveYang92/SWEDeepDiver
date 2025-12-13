from pathlib import Path


def read_content(path: Path) -> str:
    """
    read text content from path
    """
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""
