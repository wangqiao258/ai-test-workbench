from collections import defaultdict
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_membership, require_role
from app.core.errors import ApiError
from app.core.pagination import paginate
from app.core.time import utcnow
from app.db.models.asset import CaseOperationMarker
from app.db.models.case import CaseRequirementMarker, TestCase
from app.db.models.identity import ProjectMember
from app.db.session import get_db
from app.schemas.query import (
    CaseArchiveIn,
    CaseArchiveOut,
    CaseListOut,
    CaseOut,
)
from app.services.audit import record_audit
from app.services.specs import relative_spec_path

RunStatus = Literal["passed", "failed", "skipped", "error"]

router = APIRouter(prefix="/projects/{project_id}/cases", tags=["query"])

EDITOR = require_role("admin", "tester", message="当前角色无权修改用例")


@router.get("", response_model=CaseListOut)
def list_cases(
    project_id: UUID,
    q: str | None = None,
    status: RunStatus | None = None,
    requirement: str | None = None,
    operation: str | None = None,
    include_archived: bool = Query(default=False, alias="includeArchived"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> CaseListOut:
    conditions = [TestCase.project_id == project_id]
    if not include_archived:
        conditions.append(TestCase.archived_at.is_(None))
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

    cases, total = paginate(
        db,
        TestCase,
        conditions,
        (TestCase.file, TestCase.nodeid),
        page,
        page_size,
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
                spec_path=(
                    relative.as_posix()
                    if (relative := relative_spec_path(project_id, case.file))
                    else None
                ),
                tags=case.tags,
                requirement_ids=sorted(requirement_map[case.id]),
                operation_ids=sorted(operation_map[case.id]),
                last_run_id=case.last_run_id,
                last_status=case.last_status,
                last_duration_ms=case.last_duration_ms,
                last_run_at=case.last_run_at,
                archived_at=case.archived_at,
            )
            for case in cases
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.patch("", response_model=CaseArchiveOut)
def set_case_archived(
    project_id: UUID,
    payload: CaseArchiveIn,
    member: ProjectMember = Depends(EDITOR),
    db: Session = Depends(get_db),
) -> CaseArchiveOut:
    test_case = db.scalar(
        select(TestCase).where(
            TestCase.project_id == project_id, TestCase.nodeid == payload.nodeid
        )
    )
    if test_case is None:
        raise ApiError(404, "case_not_found", "用例不存在")
    test_case.archived_at = utcnow() if payload.archived else None
    record_audit(
        db,
        project_id,
        member.user_id,
        "case",
        test_case.nodeid,
        "archive" if payload.archived else "restore",
        after={"archived": payload.archived},
    )
    db.commit()
    return CaseArchiveOut(nodeid=test_case.nodeid, archived=payload.archived)
