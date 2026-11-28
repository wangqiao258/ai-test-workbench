"""按项目内业务编号加载实体，统一 404 语义。"""

from typing import TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError

T = TypeVar("T")


def load_by_external_id(
    db: Session,
    model: type[T],
    project_id: UUID,
    external_id: str,
    *,
    error_code: str,
    message: str,
) -> T:
    row = db.scalar(
        select(model).where(
            model.project_id == project_id, model.external_id == external_id
        )
    )
    if row is None:
        raise ApiError(404, error_code, message)
    return row


def load_by_number(
    db: Session,
    model: type[T],
    project_id: UUID,
    number: str,
    *,
    error_code: str,
    message: str,
) -> T:
    row = db.scalar(
        select(model).where(model.project_id == project_id, model.number == number)
    )
    if row is None:
        raise ApiError(404, error_code, message)
    return row
