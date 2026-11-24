import hashlib
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models.ingest import IdempotencyRecord


def digest_model(payload: BaseModel) -> str:
    return hashlib.sha256(payload.model_dump_json().encode("utf-8")).hexdigest()


def digest_bytes(*parts: bytes) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part)
    return hasher.hexdigest()


def begin_idempotent(
    db: Session,
    project_id: UUID,
    endpoint: str,
    key: str,
    request_digest: str,
) -> tuple[IdempotencyRecord | None, dict | None]:
    """返回 (待完成记录, 重放响应)。重放响应非空时直接返回给调用方。"""
    key = key.strip()
    if not key:
        raise ApiError(422, "missing_idempotency_key", "Idempotency-Key 不能为空")

    existing = _find(db, project_id, endpoint, key)
    if existing is not None:
        return _replay(existing, request_digest)

    record = IdempotencyRecord(
        project_id=project_id,
        endpoint=endpoint,
        idempotency_key=key,
        request_sha256=request_digest,
        status="in_progress",
        response={},
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = _find(db, project_id, endpoint, key)
        if existing is None:
            raise
        return _replay(existing, request_digest)
    return record, None


def finish_idempotent(record: IdempotencyRecord | None, response: dict) -> None:
    if record is None:
        return
    record.status = "completed"
    record.response = response


def _find(
    db: Session, project_id: UUID, endpoint: str, key: str
) -> IdempotencyRecord | None:
    return db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.project_id == project_id,
            IdempotencyRecord.endpoint == endpoint,
            IdempotencyRecord.idempotency_key == key,
        )
    )


def _replay(record: IdempotencyRecord, request_digest: str) -> tuple[None, dict]:
    if record.request_sha256 != request_digest:
        raise ApiError(
            409,
            "idempotency_conflict",
            "同一 Idempotency-Key 对应了不同的请求内容",
            details={"idempotencyKey": record.idempotency_key},
        )
    if record.status != "completed":
        raise ApiError(409, "idempotency_in_progress", "相同请求正在处理中，请稍后重试")
    return None, record.response
