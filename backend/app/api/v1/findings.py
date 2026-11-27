from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_membership
from app.core.errors import ApiError
from app.core.pagination import paginate
from app.db.models.analysis import Finding
from app.db.models.asset import Operation
from app.db.models.identity import AppUser, ProjectMember
from app.db.models.review import Defect, Judgment
from app.db.models.run import Run
from app.db.session import get_db
from app.core.security import create_ai_ticket
from app.schemas.agent import AiTicketOut
from app.schemas.review import (
    FindingDetailOut,
    FindingListOut,
    FindingStatus,
    JudgeIn,
    JudgeOut,
    JudgmentOut,
)
from app.services.idempotency import begin_idempotent, digest_model, finish_idempotent
from app.services.review import (
    actor_name,
    build_finding_out,
    judge_finding,
    resolve_finding_operation_id,
)
from app.services.runs import resolve_run

router = APIRouter(prefix="/projects/{project_id}/findings", tags=["review"])


def _load_finding(db: Session, project_id: UUID, finding_id: str) -> Finding:
    finding = db.scalar(
        select(Finding).where(
            Finding.project_id == project_id, Finding.external_id == finding_id
        )
    )
    if finding is None:
        raise ApiError(404, "finding_not_found", "AI finding 不存在")
    return finding


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
    conditions = [Finding.project_id == project_id]
    if run_id:
        run = resolve_run(db, project_id, run_id)
        conditions.append(Finding.run_id == run.id)
    if status is not None:
        conditions.append(Finding.status == status)

    findings, total = paginate(
        db,
        Finding,
        conditions,
        (Finding.created_at.desc(), Finding.external_id),
        page,
        page_size,
    )

    run_ids = {item.run_id for item in findings}
    run_map = {
        run.id: run
        for run in db.scalars(select(Run).where(Run.id.in_(run_ids)))
    } if run_ids else {}
    finding_ids = [item.id for item in findings]
    defect_map = (
        dict(
            db.execute(
                select(Defect.finding_id, Defect.number).where(
                    Defect.finding_id.in_(finding_ids)
                )
            ).all()
        )
        if finding_ids
        else {}
    )
    operations = list(
        db.scalars(select(Operation).where(Operation.project_id == project_id))
    )

    return FindingListOut(
        items=[
            build_finding_out(
                item,
                run_external_id=(
                    run_map[item.run_id].external_id if item.run_id in run_map else ""
                ),
                operation_id=resolve_finding_operation_id(db, item, operations),
                defect_number=defect_map.get(item.id),
            )
            for item in findings
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{finding_id}", response_model=FindingDetailOut)
def get_finding(
    project_id: UUID,
    finding_id: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> FindingDetailOut:
    finding = _load_finding(db, project_id, finding_id)
    run = db.get(Run, finding.run_id)
    operations = list(
        db.scalars(select(Operation).where(Operation.project_id == project_id))
    )
    defect = db.scalar(select(Defect).where(Defect.finding_id == finding.id))
    base = build_finding_out(
        finding,
        run_external_id=run.external_id if run is not None else "",
        operation_id=resolve_finding_operation_id(db, finding, operations),
        defect_number=defect.number if defect is not None else None,
    )

    rows = db.execute(
        select(Judgment, AppUser.display_name, AppUser.email)
        .outerjoin(AppUser, AppUser.id == Judgment.actor_user_id)
        .where(Judgment.finding_id == finding.id)
        .order_by(Judgment.created_at)
    ).all()
    judgments = [
        JudgmentOut(
            verdict=judgment.verdict,
            note=judgment.note,
            actor=actor_name(display_name, email),
            defect_id=defect.number if judgment.defect_id is not None and defect else None,
            created_at=judgment.created_at,
        )
        for judgment, display_name, email in rows
    ]
    return FindingDetailOut(**base.model_dump(), judgments=judgments)


@router.post("/{finding_id}/ai-ticket", response_model=AiTicketOut)
def create_finding_ai_ticket(
    project_id: UUID,
    finding_id: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> AiTicketOut:
    finding = _load_finding(db, project_id, finding_id)
    run = db.get(Run, finding.run_id)
    ttl = get_settings().ai_ticket_ttl_minutes
    ticket, expires_at = create_ai_ticket(
        project_id=project_id,
        resource=f"finding:{finding.external_id}",
        run_ref=run.external_id if run is not None else None,
        nodeid=finding.nodeid,
        ttl_minutes=ttl,
    )
    return AiTicketOut(
        url=(
            f"/ingest/v1/findings/{quote(finding.external_id, safe='')}"
            f"?ticket={quote(ticket, safe='')}"
        ),
        expires_at=expires_at,
        ttl_seconds=ttl * 60,
    )


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
