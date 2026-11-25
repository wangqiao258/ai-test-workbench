"""列表分页查询：统一 count + offset/limit，避免各路由重复实现。"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def paginate(
    db: Session,
    model: type[Any],
    conditions: list,
    order_by: tuple,
    page: int,
    page_size: int,
) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    rows = list(
        db.scalars(
            select(model)
            .where(*conditions)
            .order_by(*order_by)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return rows, total
