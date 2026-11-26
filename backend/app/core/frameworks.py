"""用例框架白名单：索引只收这些框架，其余按临时脚本处理。"""

CATALOG_FRAMEWORKS: tuple[str, ...] = (
    "pytest",
    "tavern",
    "postman",
    "playwright",
    "cypress",
)

AD_HOC_FRAMEWORK = "script"

RUN_FRAMEWORKS: tuple[str, ...] = (*CATALOG_FRAMEWORKS, AD_HOC_FRAMEWORK)


def normalize_framework(value: str | None) -> str:
    return (value or "").strip().lower()
