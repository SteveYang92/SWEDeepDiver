# 256 色快速参考：
# 红色系：196（纯红）→ 160（深红）
# 绿色系：46（亮绿）→ 28（深绿）
# 蓝色系：21（纯蓝）→ 19（深蓝）
# 灰色：244（中灰）→ 250（亮灰）

WHITE_BOLD = f"\033[1;38;5;{255}m"
GRAY_NORMAL = f"\033[38;5;{248}m"
RED_BOLD = f"\033[1;38;5;{160}m"
BLUE_BOLD = f"\033[1;38;5;{21}m"

RESET = "\033[0m"  # 重置颜色


if __name__ == "__main__":
    # 测试
    print(f"{WHITE_BOLD}白字加粗{RESET}")
    print(f"{GRAY_NORMAL}灰字正常{RESET}")
    print(f"{RED_BOLD}红字加粗{RESET}")
    print(f"{BLUE_BOLD}蓝字加粗{RESET}")

    # 灰度色代码 = 232 + 灰度级别 (0-23)
    # 使用方式：\033[38;5;<code>m (前景) 或 \033[48;5;<code>m (背景)
    # 打印所有灰度色
    for i in range(24):
        code = 232 + i
        print(f"\033[38;5;{code}m {code:3d} \033[0m", end="")
        if (i + 1) % 8 == 0:  # 每8个换行
            print()
