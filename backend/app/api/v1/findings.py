from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.core.deps import get_membership
from app.db.models.identity import ProjectMember
from app.db.session import get_db
from app.schemas.agent import AiTicketOut
from app.schemas.review import (
    FindingDetailOut,
    FindingListOut,
    FindingStatus,
    JudgeIn,
    JudgeOut,
)
from app.services.idempotency import begin_idempotent, digest_model, finish_idempotent
from app.services.review import (
    finding_ai_ticket,
    judge_finding,
    load_finding,
)
from app.services.review_views import finding_detail, findings_page

router = APIRouter(prefix="/projects/{project_id}/findings", tags=["review"])


@router.get("", response_model=FindingListOut)
def list_findings(
    project_id: UUID,
    run_id: str | None = Query(default=None, alias="runId"),
    status: FindingStatus | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> FindingListOut:
    return findings_page(
        db,
        project_id,
        run_id=run_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/{finding_id}", response_model=FindingDetailOut, deprecated=True)
def get_finding(
    project_id: UUID,
    finding_id: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> FindingDetailOut:
    return finding_detail(db, project_id, load_finding(db, project_id, finding_id))


@router.post("/{finding_id}/ai-ticket", response_model=AiTicketOut)
def create_finding_ai_ticket(
    project_id: UUID,
    finding_id: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> AiTicketOut:
    return finding_ai_ticket(db, load_finding(db, project_id, finding_id))


@router.post("/{finding_id}/judge", response_model=JudgeOut)
def judge(
    project_id: UUID,
    finding_id: str,
    payload: JudgeIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> JudgeOut:
    record = None
    if idempotency_key:
        record, replay = begin_idempotent(
            db, project_id, "judge", idempotency_key, digest_model(payload)
        )
        if replay is not None:
            return JudgeOut(**replay)

    result = judge_finding(
        db,
        project_id,
        finding_id,
        payload.verdict,
        payload.note,
        member.user_id,
    )
    if record is not None:
        finish_idempotent(record, result.model_dump(mode="json"))
    db.commit()
    return result
