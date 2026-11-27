"""供 AI 机 / 外部分析流水线只读访问项目资产。

与前端使用的 /api/v1 查询接口返回同一套结构，只是改用项目 Token 认证。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import (
    SCOPE_ASSETS_READ,
    SCOPE_RUNS_READ,
    require_token_scope,
)
from app.db.models.project import Project
from app.db.models.run import Run
from app.db.session import get_db
from app.schemas.query import OpenApiDocOut, RequirementOut, RunOut
from app.services.asset_views import openapi_doc_outs, requirement_outs
from app.services.runs import run_out

router = APIRouter(prefix="/assets", tags=["ingest"])


@router.get("/requirements", response_model=list[RequirementOut])
def read_requirements(
    project: Project = Depends(require_token_scope(SCOPE_ASSETS_READ)),
    db: Session = Depends(get_db),
) -> list[RequirementOut]:
    return requirement_outs(db, project.id)


@router.get("/openapi", response_model=list[OpenApiDocOut])
def read_openapi_docs(
    project: Project = Depends(require_token_scope(SCOPE_ASSETS_READ)),
    db: Session = Depends(get_db),
) -> list[OpenApiDocOut]:
    return openapi_doc_outs(db, project.id)


@router.get("/runs", response_model=list[RunOut])
def read_runs(
    limit: int = Query(default=20, ge=1, le=100),
    project: Project = Depends(require_token_scope(SCOPE_RUNS_READ)),
    db: Session = Depends(get_db),
) -> list[RunOut]:
    runs = list(
        db.scalars(
            select(Run)
            .where(Run.project_id == project.id)
            .order_by(Run.started_at.desc(), Run.created_at.desc())
            .limit(limit)
        )
    )
    return [run_out(run) for run in runs]
