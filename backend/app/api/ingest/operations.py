"""AI 机按需检索接口：先摘要，再取单个接口详情，避免拉取全量 OpenAPI。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.defaults import OPERATIONS_PAGE_SIZE
from app.core.deps import SCOPE_ASSETS_READ, require_token_scope
from app.db.models.project import Project
from app.db.session import get_db
from app.schemas.query import OperationOut, OperationSummaryListOut
from app.services.asset_views import operation_out_one, operations_page
from app.services.assets import get_operation as load_operation

router = APIRouter(prefix="/operations", tags=["ingest"])


@router.get("", response_model=OperationSummaryListOut)
def list_operations(
    tag: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=OPERATIONS_PAGE_SIZE, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project: Project = Depends(require_token_scope(SCOPE_ASSETS_READ)),
    db: Session = Depends(get_db),
) -> OperationSummaryListOut:
    return operations_page(
        db,
        project.id,
        tag=tag,
        q=q,
        limit=limit,
        offset=offset,
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
