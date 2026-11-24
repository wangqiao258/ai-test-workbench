import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models.analysis import Finding
from app.db.models.asset import CaseOperationMarker, Operation
from app.db.models.project import Project
from app.db.models.review import AuditLog, Defect, DefectEvent, Judgment
from app.db.models.run import Exchange, Run, RunCase
from app.schemas.review import DefectDecisionOut, DefectOut, FindingOut, JudgeOut
from app.services.operations import compile_path

DEFECT_TRANSITIONS: dict[str, set[str]] = {
    "new": {"confirmed", "closed"},
    "confirmed": {"fixing", "closed"},
    "fixing": {"fixed", "closed"},
    "fixed": {"closed"},
    "closed": set(),
}

VERDICT_STATUS = {
    "confirm": "confirmed",
    "reject": "rejected",
    "false-positive": "false-positive",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in DEFECT_TRANSITIONS.get(from_status, set())


def resolve_finding_operation_id(
    db: Session, finding: Finding, operations: list[Operation] | None = None
) -> str | None:
    if operations is None:
        operations = list(
            db.scalars(select(Operation).where(Operation.project_id == finding.project_id))
        )
    run_case_id = finding.run_case_id
    if run_case_id is None:
        run_case = db.scalar(
            select(RunCase).where(
                RunCase.run_id == finding.run_id, RunCase.nodeid == finding.nodeid
            )
        )
    else:
        run_case = db.get(RunCase, run_case_id)

    if run_case is not None and finding.exchange_index is not None:
        exchange = db.scalar(
            select(Exchange).where(
                Exchange.run_case_id == run_case.id,
                Exchange.exchange_index == finding.exchange_index,
            )
        )
        if exchange is not None:
            for operation in operations:
                if (
                    operation.method.upper() == exchange.method.upper()
                    and compile_path(operation.path).fullmatch(exchange.path_norm)
                ):
                    return operation.external_id

    if run_case is not None and run_case.case_id is not None:
        markers = list(
            db.scalars(
                select(CaseOperationMarker).where(
                    CaseOperationMarker.case_id == run_case.case_id
                )
            )
        )
        if len(markers) == 1:
            return markers[0].operation_external_id
    return None


def build_finding_out(
    finding: Finding,
    *,
    run_external_id: str,
    operation_id: str | None,
    defect_number: str | None,
) -> FindingOut:
    return FindingOut(
        id=finding.external_id,
        run_id=finding.run_id,
        run_external_id=run_external_id,
        nodeid=finding.nodeid,
        type=finding.type,
        title=finding.title,
        summary=finding.summary,
        root_cause=finding.root_cause,
        impact=finding.impact,
        confidence=finding.confidence,
        suggested_severity=finding.suggested_severity,
        exchange_index=finding.exchange_index,
        requirement_id=finding.requirement_external_id,
        operation_id=operation_id,
        status=finding.status,
        note=finding.note,
        judged_at=finding.judged_at,
        defect_id=defect_number,
        created_at=finding.created_at,
    )


def build_defect_out(
    defect: Defect,
    *,
    finding_external_id: str | None,
    run_external_id: str | None,
) -> DefectOut:
    return DefectOut(
        id=defect.number,
        title=defect.title,
        severity=defect.severity,
        status=defect.status,
        finding_id=finding_external_id,
        run_id=defect.run_id,
        run_external_id=run_external_id,
        nodeid=defect.nodeid,
        requirement_id=defect.requirement_external_id,
        operation_id=defect.operation_external_id,
        exchange_index=defect.exchange_index,
        evidence_summary=defect.evidence_summary,
        source=defect.source,
        decision=DefectDecisionOut(
            verdict=defect.decision_verdict,
            note=defect.decision_note,
            at=defect.decided_at,
        ),
        version=defect.version,
        created_at=defect.created_at,
        updated_at=defect.updated_at,
    )


def _evidence_summary(run: Run | None, finding: Finding) -> str:
    run_id = run.external_id if run is not None else str(finding.run_id)
    if finding.exchange_index is not None:
        return f"{run_id} / {finding.nodeid} / 第 {finding.exchange_index + 1} 次交换"
    return f"{run_id} / {finding.nodeid}"


def _change_defect_status(
    db: Session,
    defect: Defect,
    to_status: str,
    actor_user_id: uuid.UUID,
    note: str,
) -> None:
    from_status = defect.status
    old_version = defect.version
    defect.status = to_status
    defect.version = old_version + 1
    db.add(
        DefectEvent(
            project_id=defect.project_id,
            defect_id=defect.id,
            from_status=from_status,
            to_status=to_status,
            note=note,
            actor_user_id=actor_user_id,
        )
    )
    db.add(
        AuditLog(
            project_id=defect.project_id,
            entity_type="defect",
            entity_id=defect.number,
            action="status_change",
            actor_user_id=actor_user_id,
            before={"status": from_status, "version": old_version},
            after={"status": to_status, "version": defect.version, "note": note},
        )
    )


def judge_finding(
    db: Session,
    project_id: uuid.UUID,
    finding_external_id: str,
    verdict: str,
    note: str,
    actor_user_id: uuid.UUID,
) -> JudgeOut:
    finding = db.execute(
        select(Finding)
        .where(Finding.project_id == project_id, Finding.external_id == finding_external_id)
        .with_for_update()
    ).scalar_one_or_none()
    if finding is None:
        raise ApiError(404, "finding_not_found", "AI finding 不存在")

    now = _utcnow()
    run = db.get(Run, finding.run_id)
    operations = list(
        db.scalars(select(Operation).where(Operation.project_id == project_id))
    )
    operation_id = resolve_finding_operation_id(db, finding, operations)
    defect = db.scalar(select(Defect).where(Defect.finding_id == finding.id))
    audit_before = {
        "status": finding.status,
        "note": finding.note,
        "defectId": defect.number if defect is not None else None,
    }

    if verdict == "confirm":
        if defect is None:
            project = db.execute(
                select(Project).where(Project.id == project_id).with_for_update()
            ).scalar_one()
            project.defect_seq += 1
            defect = Defect(
                project_id=project_id,
                number=f"DEF-{project.defect_seq:04d}",
                finding_id=finding.id,
                run_id=finding.run_id,
                nodeid=finding.nodeid,
                exchange_index=finding.exchange_index,
                requirement_external_id=finding.requirement_external_id,
                operation_external_id=operation_id,
                title=finding.title,
                severity=finding.suggested_severity,
                status="new",
                evidence_summary=_evidence_summary(run, finding),
                source="AI 审判",
                decision_verdict=verdict,
                decision_note=note,
                decided_at=now,
                version=1,
            )
            db.add(defect)
            db.flush()
            db.add(
                DefectEvent(
                    project_id=project_id,
                    defect_id=defect.id,
                    from_status=None,
                    to_status="new",
                    note="finding 确认后生成",
                    actor_user_id=actor_user_id,
                )
            )
            db.add(
                AuditLog(
                    project_id=project_id,
                    entity_type="defect",
                    entity_id=defect.number,
                    action="create",
                    actor_user_id=actor_user_id,
                    before=None,
                    after={"status": "new", "findingId": finding.external_id},
                )
            )
        elif defect.status == "closed":
            _change_defect_status(
                db, defect, "new", actor_user_id, note="重新确认 finding，缺陷重新打开"
            )
    elif defect is not None and defect.status != "closed":
        _change_defect_status(
            db, defect, "closed", actor_user_id, note="finding 复议驳回，关闭缺陷"
        )

    finding.status = VERDICT_STATUS[verdict]
    finding.note = note
    finding.judged_at = now
    db.add(
        Judgment(
            project_id=project_id,
            finding_id=finding.id,
            defect_id=defect.id if defect is not None else None,
            verdict=verdict,
            note=note,
            actor_user_id=actor_user_id,
        )
    )
    db.add(
        AuditLog(
            project_id=project_id,
            entity_type="finding",
            entity_id=finding.external_id,
            action="judge",
            actor_user_id=actor_user_id,
            before=audit_before,
            after={
                "status": finding.status,
                "note": note,
                "verdict": verdict,
                "defectId": defect.number if defect is not None else None,
            },
        )
    )
    db.flush()

    return JudgeOut(
        finding=build_finding_out(
            finding,
            run_external_id=run.external_id if run is not None else "",
            operation_id=operation_id,
            defect_number=defect.number if defect is not None else None,
        ),
        defect=build_defect_out(
            defect,
            finding_external_id=finding.external_id,
            run_external_id=run.external_id if run is not None else None,
        )
        if defect is not None
        else None,
    )


def update_defect_status(
    db: Session,
    project_id: uuid.UUID,
    defect_number: str,
    to_status: str,
    version: int | None,
    actor_user_id: uuid.UUID,
) -> Defect:
    defect = db.execute(
        select(Defect)
        .where(Defect.project_id == project_id, Defect.number == defect_number)
        .with_for_update()
    ).scalar_one_or_none()
    if defect is None:
        raise ApiError(404, "defect_not_found", "缺陷不存在")
    if version is not None and defect.version != version:
        raise ApiError(
            409,
            "version_conflict",
            "缺陷已被其他人更新，请刷新后重试",
            details={"expected": defect.version, "received": version},
        )
    if defect.status == to_status:
        return defect
    if not can_transition(defect.status, to_status):
        raise ApiError(
            409,
            "invalid_defect_transition",
            f"缺陷状态不能从 {defect.status} 流转到 {to_status}",
            details={"from": defect.status, "to": to_status},
        )
    _change_defect_status(db, defect, to_status, actor_user_id, note="人工更新缺陷状态")
    db.flush()
    return defect
