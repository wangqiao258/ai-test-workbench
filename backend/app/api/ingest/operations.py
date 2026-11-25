"""AI 机按需检索接口：先摘要，再取单个接口详情，避免拉取全量 OpenAPI。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.defaults import OPERATIONS_PAGE_SIZE
from app.core.deps import SCOPE_ASSETS_READ, require_token_scope
from app.db.models.asset import OpenApiDoc, Operation
from app.db.models.project import Project
from app.db.session import get_db
from app.schemas.query import (
    OperationOut,
    OperationSummaryListOut,
    OperationSummaryOut,
)
from app.services.asset_views import operation_out_one
from app.services.assets import get_operation as load_operation

router = APIRouter(prefix="/operations", tags=["ingest"])


def _summary(item: Operation, doc_id: str) -> OperationSummaryOut:
    params = item.params or []
    body = item.request_body or []
    statuses = sorted(
        {
            response.get("status")
            for response in (item.responses or [])
            if isinstance(response.get("status"), int)
        }
    )
    return OperationSummaryOut(
        id=item.external_id,
        doc_id=doc_id,
        method=item.method,
        path=item.path,
        summary=item.summary,
        tag=item.tag,
        description_preview=" ".join((item.description or "").split())[:200],
        required_params=[
            {
                "name": param.get("name", ""),
                "in": param.get("in", ""),
                "type": param.get("type", ""),
            }
            for param in params
            if param.get("required")
        ],
        optional_param_count=sum(1 for param in params if not param.get("required")),
        request_body_fields=[
            {
                "name": field.get("name", ""),
                "type": field.get("type", ""),
                "required": bool(field.get("required")),
            }
            for field in body[:10]
        ],
        request_body_field_count=len(body),
        response_statuses=statuses,
    )


@router.get("", response_model=OperationSummaryListOut)
def list_operations(
    tag: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=OPERATIONS_PAGE_SIZE, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project: Project = Depends(require_token_scope(SCOPE_ASSETS_READ)),
    db: Session = Depends(get_db),
) -> OperationSummaryListOut:
    conditions = [Operation.project_id == project.id]
    if tag:
        conditions.append(Operation.tag == tag)
    if q:
        like = f"%{q}%"
        conditions.append(
            or_(
                Operation.path.ilike(like),
                Operation.summary.ilike(like),
                Operation.external_id.ilike(like),
            )
        )

    total = db.scalar(select(func.count(Operation.id)).where(*conditions)) or 0
    doc_ids = dict(
        db.execute(
            select(OpenApiDoc.id, OpenApiDoc.external_id).where(
                OpenApiDoc.project_id == project.id
            )
        ).all()
    )
    rows = db.scalars(
        select(Operation)
        .where(*conditions)
        .order_by(Operation.tag, Operation.path, Operation.external_id)
        .offset(offset)
        .limit(limit)
    ).all()
    next_offset = offset + limit if offset + limit < total else None
    return OperationSummaryListOut(
        items=[
            _summary(item, doc_ids.get(item.doc_id, str(item.doc_id)))
            for item in rows
        ],
        total=total,
        next_offset=next_offset,
    )


@router.get("/{operation_id}", response_model=OperationOut)
def get_operation(
    operation_id: str,
    project: Project = Depends(require_token_scope(SCOPE_ASSETS_READ)),
    db: Session = Depends(get_db),
) -> OperationOut:
    return operation_out_one(
        db, project.id, load_operation(db, project.id, operation_id)
    )
