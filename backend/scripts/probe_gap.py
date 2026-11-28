"""临时探针：验证 scripts/ 目录增长会被拦截。"""


def probe() -> int:
    total = 0
    for i in range(10):
        total += i
    return total
