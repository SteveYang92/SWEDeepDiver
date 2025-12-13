import time
from functools import wraps


def measue_time(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        print(f"{func.__name__} cost: {auto_time_unit(end - start)}")
        return result

    return wrapper


def auto_time_unit(seconds: float) -> str:
    """
    根据秒数自动选择单位并格式化输出。
    小于 60 s → 显示秒（单位 s）
    大于等于 60 s → 显示分钟（单位 min）
    """
    if seconds < 60:
        return f"{seconds:.0f} s"
    return f"{seconds / 60:.1f} min"
