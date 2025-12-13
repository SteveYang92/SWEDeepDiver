from pathlib import Path
import re
import shutil
import subprocess
from typing import List, Optional

MAX_BYTES = 200_000  # 单次工具返回最大字节
TIMEOUT_S = 8  # 单次工具超时时间


def grep_file(
    path: str,
    pattern: str,
    icase: bool = True,
    before: int = 0,
    after: int = 0,
    max_matches: int = 500,
    log_sandbox_dirs: list[str] = [],
) -> str:
    if not _is_in_roots(p=path, log_sandbox_dirs=log_sandbox_dirs):
        return "[tool] path not allowed"
    if _check_ripgrep():
        return _grep_with_ripgrep(
            path=path, pattern=pattern, before=before, after=after
        )
    return _grep_with_grep(path, pattern, icase, before, after, max_matches)


def apply_time_filter(content: str, time_range: str) -> str:
    """基于时间范围过滤结果"""
    if not content:
        return ""

    start_str, end_str = time_range.split("-")

    filtered_lines = []
    for line in content.split("\n"):
        # 匹配时间格式: HH:mm:ss 或 HH:mm:ss.SSS
        time_match = re.search(r"(\d{2}:\d{2}:\d{2}(?:\.\d+)?)", line)
        if time_match and start_str <= time_match.group(1) <= end_str:
            filtered_lines.append(line)

    return "\n".join(filtered_lines)


def _is_in_roots(p: str, log_sandbox_dirs: list[str]) -> bool:
    try:
        rp = Path(p).resolve()
        for r in log_sandbox_dirs:
            if rp.is_relative_to(Path(r).resolve()):
                return True
        return False
    except Exception:
        return False


def _limit(s: str) -> str:
    if len(s.encode("utf-8", "ignore")) > MAX_BYTES:
        # 尾部截断，通常更接近问题发生区
        return s.encode("utf-8", "ignore")[-MAX_BYTES:].decode("utf-8", "ignore")
    return s


def _run(args: List[str], cwd: Optional[str] = None) -> str:
    try:
        out = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_S
        )
        data = (out.stdout or "") + ("\n" + out.stderr if out.stderr else "")
        return _limit(data)
    except subprocess.TimeoutExpired as e:
        print(f"[tool] Timeout: {e}")
    except Exception as e:
        print(f"[tool] Error: {e}")


def _check_ripgrep() -> bool:
    """快速检查ripgrep是否可用"""
    return shutil.which("rg") is not None


def _grep_with_ripgrep(
    path: str,
    pattern: str,
    icase: bool = True,
    before: int = 0,
    after: int = 0,
    max_matches: int = 500,
) -> str:
    """
    通过ripgrep进行搜索
    """
    # 启用PCRE2引擎
    args = ["rg", "-P"]
    if before > 0:
        args += ["-B", str(before)]
    if after > 0:
        args += ["-A", str(after)]
    args.append(pattern)
    args.append(path)
    return _run(args)


def _grep_with_grep(
    path: str,
    pattern: str,
    icase: bool = True,
    before: int = 0,
    after: int = 0,
    max_matches: int = 500,
) -> str:
    """
    通过grep进行搜索
    """
    args = ["grep", "-n"]
    if icase:
        args.append("-i")
    if before > 0:
        args += ["-B", str(before)]
    if after > 0:
        args += ["-A", str(after)]
    if max_matches:
        args += ["-m", str(max_matches)]
    # 使用扩展正则表达式如果模式需要
    if _needs_ere(pattern):
        args.append("-E")
    args.append(pattern)
    args.append(path)
    return _run(args)


def _needs_ere(pattern: str) -> bool:
    """判断是否需要扩展正则表达式（ERE）"""
    # 检测ERE语法特征
    ere_patterns = [
        r"\|",  # 或运算符
        r"\+",  # 一个或多个
        r"\?",  # 零个或一个
        r"\(\)",  # 空分组
        r"\{\d+(,\d*)?\}",  # 量词 {n}, {n,}, {n,m}
    ]

    for ere_pat in ere_patterns:
        if re.search(ere_pat, pattern):
            return True
    return False
