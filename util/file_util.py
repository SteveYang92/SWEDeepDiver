from pathlib import Path


def read_content(path: Path) -> str:
    """
    read text content from path
    """
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""

def is_in_roots(p: str, root_dirs: list[str]) -> bool:
    try:
        rp = Path(p).resolve()
        for r in root_dirs:
            if rp.is_relative_to(Path(r).resolve()):
                return True
        return False
    except Exception:
        return False