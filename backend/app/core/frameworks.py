"""用例框架：索引接受任意框架名，script 专用于临时脚本。"""

# 推荐用的规范框架名，仅用于 whoami 提示，不再作为白名单限制。
KNOWN_FRAMEWORKS: tuple[str, ...] = (
    "pytest",
    "tavern",
    "postman",
    "playwright",
    "cypress",
)

AD_HOC_FRAMEWORK = "script"
MAX_FRAMEWORK_LENGTH = 32


def normalize_framework(value: str | None) -> str:
    return (value or "").strip().lower()
