import re
from app.config import config

DEF_CHAR_COUNT_PER_LINE = config.log_processor.max_char_count_per_line
IGNORE_LINE_PATTERN = [
    re.compile(pattern) for pattern in config.log_processor.ignore_patterns if pattern
]


def truncate_log_omit_edges(
    log_text, n, omit_marker="(日志过多，省略{position}{count}行)"
):
    """
    保留中间 n 行日志内容，前后添加省略标记（不计入 n 行限制）

    Args:
        log_text: 日志文本字符串
        n: 保留的中间日志行数（必须≥1）
        omit_marker: 省略标记模板

    Returns:
        处理后的日志文本（总行为 n+2、n+1 或更少）
    """
    if n < 1:
        raise ValueError("n必须至少为1")

    # 处理空文本
    if not log_text or not log_text.strip():
        return log_text

    lines = [line for line in log_text.splitlines() if _filter_line(line)]
    truncated_lines = [truncate_line(line) for line in lines]
    total_lines = len(truncated_lines)

    # 如果未超过限制，直接返回原文本（不添加省略行）
    if total_lines <= n:
        return "\n".join(truncated_lines)

    # 特殊情况：n=1（保留1行，总输出3行）
    if n == 1:
        middle_idx = total_lines // 2
        head_omit = middle_idx
        tail_omit = total_lines - middle_idx - 1

        return "\n".join(
            [
                omit_marker.format(position="头部", count=head_omit),
                truncated_lines[middle_idx],
                omit_marker.format(position="尾部", count=tail_omit),
            ]
        )

    # 一般情况：n >= 2（保留n行，总输出n+2行）
    # 计算需要省略的总行数
    omit_total = total_lines - n

    # 计算省略的头部和尾部分别多少行
    head_omit = omit_total // 2
    tail_omit = omit_total - head_omit  # 处理奇数情况

    # 计算中间部分的起止索引
    middle_start = head_omit
    middle_end = total_lines - tail_omit

    # 构建结果：头部标记 + 中间内容 + 尾部标记
    result_lines = [
        omit_marker.format(position="头部", count=head_omit),
        *truncated_lines[middle_start:middle_end],
        omit_marker.format(position="尾部", count=tail_omit),
    ]

    return "\n".join(result_lines)


def truncate_line(line: str, max_length: int = DEF_CHAR_COUNT_PER_LINE) -> str:
    """截断单行，返回(处理后的行, 是否被截断)"""
    if len(line) <= max_length:
        return line

    keep_len = max_length - 15  # 保留15字符给截断标记
    return f"{line[:keep_len]}[...截断]"


def _filter_line(line) -> bool:
    for pattern in IGNORE_LINE_PATTERN:
        if pattern.search(line):
            return False
    return True


# ========== 使用示例 ==========
if __name__ == "__main__":
    # 模拟100行日志
    log_text = "\n".join([f"日志内容 {i:03d}" for i in range(1, 101)])

    print("=" * 60)
    print("保留中间10行（总输出12行）:")
    print("=" * 60)
    result = truncate_log_omit_edges(log_text, 10)
    print(result)
    print(f"\n总输出行数: {len(result.splitlines())}")
    print(f"保留的中间行数: {len(result.splitlines()) - 2}")

    print("\n" + "=" * 60)
    print("保留中间5行（总输出7行）:")
    print("=" * 60)
    result = truncate_log_omit_edges(log_text, 5)
    print(result)
    print(f"\n总输出行数: {len(result.splitlines())}")

    print("\n" + "=" * 60)
    print("保留中间1行（总输出3行）:")
    print("=" * 60)
    result = truncate_log_omit_edges(log_text, 1)
    print(result)
    print(f"\n总输出行数: {len(result.splitlines())}")

    # 测试未超过限制的情况
    print("\n" + "=" * 60)
    print("日志只有5行，保留10行（未超过限制，直接返回5行）:")
    print("=" * 60)
    short_log = "\n".join([f"日志 {i}" for i in range(1, 6)])
    result = truncate_log_omit_edges(short_log, 10)
    print(result)
    print(f"\n总输出行数: {len(result.splitlines())}")
