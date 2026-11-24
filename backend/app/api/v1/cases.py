from collections import defaultdict
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_membership
from app.db.models.asset import CaseOperationMarker
from app.db.models.case import CaseRequirementMarker, TestCase
from app.db.models.identity import ProjectMember
from app.db.session import get_db
from app.schemas.query import CaseListOut, CaseOut

RunStatus = Literal["passed", "failed", "skipped", "error"]

router = APIRouter(prefix="/projects/{project_id}/cases", tags=["query"])


@router.get("", response_model=CaseListOut)
def list_cases(
    project_id: UUID,
    q: str | None = None,
    status: RunStatus | None = None,
    requirement: str | None = None,
    operation: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> CaseListOut:
    conditions = [TestCase.project_id == project_id]
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                TestCase.nodeid.ilike(pattern),
                TestCase.name.ilike(pattern),
                TestCase.file.ilike(pattern),
            )
        )
    if status is not None:
        conditions.append(TestCase.last_status == status)
    if requirement:
        conditions.append(
            TestCase.id.in_(
                select(CaseRequirementMarker.case_id).where(
                    CaseRequirementMarker.project_id == project_id,
                    CaseRequirementMarker.requirement_external_id == requirement,
                )
            )
        )
    if operation:
        conditions.append(
            TestCase.id.in_(
                select(CaseOperationMarker.case_id).where(
                    CaseOperationMarker.project_id == project_id,
                    CaseOperationMarker.operation_external_id == operation,
                )
            )
        )

    total = (
        db.scalar(select(func.count(TestCase.id)).where(*conditions)) or 0
    )
    cases = list(
        db.scalars(
            select(TestCase)
            .where(*conditions)
            .order_by(TestCase.file, TestCase.nodeid)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )

    case_ids = [case.id for case in cases]
    requirement_map: dict[UUID, list[str]] = defaultdict(list)
    operation_map: dict[UUID, list[str]] = defaultdict(list)
    if case_ids:
        for case_id, external_id in db.execute(
            select(
                CaseRequirementMarker.case_id,
                CaseRequirementMarker.requirement_external_id,
            ).where(CaseRequirementMarker.case_id.in_(case_ids))
        ).all():
            requirement_map[case_id].append(external_id)
        for case_id, external_id in db.execute(
            select(
                CaseOperationMarker.case_id,
                CaseOperationMarker.operation_external_id,
            ).where(CaseOperationMarker.case_id.in_(case_ids))
        ).all():
            operation_map[case_id].append(external_id)

    return CaseListOut(
        items=[
            CaseOut(
                nodeid=case.nodeid,
                name=case.name,
                file=case.file,
                tags=case.tags,
                requirement_ids=sorted(requirement_map[case.id]),
                operation_ids=sorted(operation_map[case.id]),
                last_run_id=case.last_run_id,
                last_status=case.last_status,
                last_duration_ms=case.last_duration_ms,
                last_run_at=case.last_run_at,
            )
            for case in cases
        ],
        page=page,
        page_size=page_size,
        total=total,
    )
