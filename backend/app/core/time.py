from datetime import datetime, timezone


def utcnow() -> datetime:
    """带时区的当前时间，统一各模块的时间来源。"""
    return datetime.now(timezone.utc)
