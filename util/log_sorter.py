from datetime import datetime
import re

def sort_logs_with_stacktrace(logs: str, reverse: bool = False) -> str:
    """
    按时间块排序日志，保持堆栈/详细信息与主日志在一起
    
    :param logs: 原始日志字符串
    :param reverse: 是否降序（True=最新在前）
    """
    
    # 识别时间戳的正则（你的格式：2025-07-18 15:46:02.330）
    TIMESTAMP_PATTERN = r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}'
    
    def has_timestamp(line: str) -> bool:
        """检查行是否包含时间戳"""
        return bool(re.match(TIMESTAMP_PATTERN, line))
    
    def parse_timestamp(line: str) -> datetime:
        """从行首解析时间戳"""
        try:
            time_str = line[:23]  # 精确截取时间部分
            return datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S.%f')
        except (ValueError, IndexError):
            return datetime.min  # 无效时间返回最小值
    
    # Step 1: 将日志拆分为块（每个时间戳行+其堆栈信息）
    blocks = []
    current_block = None
    
    for line in logs.split('\n'):
        line = line.rstrip()
        if not line:
            continue
        
        if has_timestamp(line):
            # 开始新块
            if current_block:
                blocks.append(current_block)
            
            current_block = {
                'timestamp': parse_timestamp(line),
                'lines': [line]  # 包含时间戳行
            }
        else:
            # 添加到当前块的堆栈信息
            if current_block:
                current_block['lines'].append(line)
    
    # 添加最后一个块
    if current_block:
        blocks.append(current_block)
    
    # Step 2: 按时间戳排序块
    sorted_blocks = sorted(blocks, key=lambda b: b['timestamp'], reverse=reverse)
    
    # Step 3: 重构日志字符串
    sorted_lines = []
    for block in sorted_blocks:
        sorted_lines.extend(block['lines'])
    
    return '\n'.join(sorted_lines)
