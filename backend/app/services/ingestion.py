import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.time import utcnow
from app.db.models.analysis import Analysis, Finding
from app.db.models.case import TestCase
from app.db.models.run import Artifact, Exchange, Run, RunCase
from app.schemas.ingest import (
    AnalysisIn,
    AnalysisOut,
    CaseBase,
    CaseIn,
    CatalogIn,
    CatalogOut,
    ExchangeIn,
    RunIngestIn,
    RunIngestOut,
)
from app.services.case_markers import replace_requirement_markers
from app.services.har import normalized_path
from app.services.operations import rebuild_case_operation_markers
from app.services.storage import LocalStorage

BODY_INLINE_LIMIT = 64 * 1024


def ingest_run(
    db: Session, project_id: uuid.UUID, payload: RunIngestIn, storage: LocalStorage
) -> RunIngestOut:
    run = db.scalar(
        select(Run).where(Run.project_id == project_id, Run.external_id == payload.run.external_id)
    )
    if run is None:
        run = Run(
            project_id=project_id,
            external_id=payload.run.external_id,
            started_at=payload.run.started_at,
            duration_ms=payload.run.duration_ms,
            branch=payload.run.branch,
            commit_sha=payload.run.commit,
            environment=payload.run.environment,
            stats={},
        )
        db.add(run)
    else:
        run.started_at = payload.run.started_at
        run.duration_ms = payload.run.duration_ms
        run.branch = payload.run.branch
        run.commit_sha = payload.run.commit
        run.environment = payload.run.environment
    db.flush()

    stats = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 0}
    exchange_count = 0
    seen_nodeids: list[str] = []
    affected_case_ids: list[uuid.UUID] = []

    for case in payload.cases:
        test_case = _upsert_test_case(db, project_id, case, run)
        affected_case_ids.append(test_case.id)
        run_case = db.scalar(
            select(RunCase).where(RunCase.run_id == run.id, RunCase.nodeid == case.nodeid)
        )
        if run_case is None:
            run_case = RunCase(run_id=run.id, project_id=project_id, nodeid=case.nodeid)
            db.add(run_case)
        run_case.case_id = test_case.id
        run_case.status = case.status
        run_case.duration_ms = case.duration_ms
        run_case.error_text = case.error
        run_case.logs = case.logs
        db.flush()

        replace_requirement_markers(db, project_id, test_case.id, case.requirements)
        exchange_count += replace_exchanges(
            db, storage, project_id, run.id, run_case.id, case.exchanges
        )

        seen_nodeids.append(case.nodeid)
        stats["total"] += 1
        stats[case.status] += 1

    if seen_nodeids:
        db.execute(
            delete(RunCase).where(
                RunCase.run_id == run.id, RunCase.nodeid.notin_(seen_nodeids)
            )
        )
    else:
        db.execute(delete(RunCase).where(RunCase.run_id == run.id))

    rebuild_case_operation_markers(db, project_id, affected_case_ids)

    run.stats = stats
    if payload.analysis is not None:
        finding_count = _upsert_analysis(db, project_id, run, payload.analysis)
    else:
        finding_count = 0
    run.updated_at = utcnow()
    db.flush()

    return RunIngestOut(
        run_id=run.id,
        external_id=run.external_id,
        case_count=len(payload.cases),
        exchange_count=exchange_count,
        finding_count=finding_count,
    )


def ingest_analysis(
    db: Session, project_id: uuid.UUID, run: Run, payload: AnalysisIn
) -> AnalysisOut:
    finding_count = _upsert_analysis(db, project_id, run, payload)
    db.flush()
    return AnalysisOut(run_id=run.id, finding_count=finding_count)


def _upsert_case(
    db: Session, project_id: uuid.UUID, case: CaseBase, now: datetime
) -> TestCase:
    test_case = db.scalar(
        select(TestCase).where(
            TestCase.project_id == project_id, TestCase.nodeid == case.nodeid
        )
    )
    if test_case is None:
        test_case = TestCase(
            project_id=project_id,
            nodeid=case.nodeid,
            file=case.file or case.nodeid.split("::", 1)[0],
            name=case.name or case.nodeid.split("::")[-1],
            tags=case.tags,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(test_case)
        db.flush()
    else:
        test_case.file = case.file or test_case.file
        test_case.name = case.name or test_case.name
        test_case.tags = case.tags
        test_case.last_seen_at = now
    return test_case


def upsert_catalog(db: Session, project_id: uuid.UUID, payload: CatalogIn) -> CatalogOut:
    now = utcnow()
    marker_count = 0
    affected_case_ids: list[uuid.UUID] = []
    for case in payload.cases:
        test_case = _upsert_case(db, project_id, case, now)
        affected_case_ids.append(test_case.id)
        marker_count += replace_requirement_markers(
            db, project_id, test_case.id, case.requirements
        )
    rebuild_case_operation_markers(db, project_id, affected_case_ids)
    return CatalogOut(case_count=len(payload.cases), marker_count=marker_count)


def _upsert_test_case(
    db: Session, project_id: uuid.UUID, case: CaseIn, run: Run
) -> TestCase:
    test_case = _upsert_case(db, project_id, case, utcnow())

    if test_case.last_run_at is None or run.started_at >= test_case.last_run_at:
        test_case.last_run_id = run.id
        test_case.last_status = case.status
        test_case.last_duration_ms = case.duration_ms
        test_case.last_run_at = run.started_at
    return test_case


def replace_exchanges(
    db: Session,
    storage: LocalStorage,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    run_case_id: uuid.UUID,
    exchanges: list[ExchangeIn],
) -> int:
    db.execute(delete(Exchange).where(Exchange.run_case_id == run_case_id))
    for exchange in exchanges:
        request_body, request_body_artifact_id = _store_body(
            db, storage, project_id, run_id, run_case_id, exchange.index, "request", exchange.request.body
        )
        response_body, response_body_artifact_id = _store_body(
            db,
            storage,
            project_id,
            run_id,
            run_case_id,
            exchange.index,
            "response",
            exchange.response.body,
        )
        db.add(
            Exchange(
                run_id=run_id,
                run_case_id=run_case_id,
                exchange_index=exchange.index,
                method=exchange.method.upper(),
                url=exchange.url,
                path_norm=normalized_path(exchange.url),
                status_code=exchange.status,
                elapsed_ms=exchange.elapsed_ms,
                request_headers=[header.model_dump() for header in exchange.request.headers],
                request_body=request_body,
                request_body_artifact_id=request_body_artifact_id,
                response_headers=[header.model_dump() for header in exchange.response.headers],
                response_body=response_body,
                response_body_artifact_id=response_body_artifact_id,
                error_text=exchange.error,
            )
        )
    db.flush()
    return len(exchanges)


def _store_body(
    db: Session,
    storage: LocalStorage,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    run_case_id: uuid.UUID,
    index: int,
    side: str,
    body: str | None,
) -> tuple[str | None, uuid.UUID | None]:
    if body is None:
        return None, None
    encoded = body.encode("utf-8")
    if len(encoded) <= BODY_INLINE_LIMIT:
        return body, None
    filename = f"{index}-{side}.txt"
    key, size, sha256 = storage.save(
        project_id, run_id, filename, encoded, content_type="text/plain"
    )
    artifact = Artifact(
        project_id=project_id,
        run_id=run_id,
        run_case_id=run_case_id,
        kind="body",
        storage_key=key,
        filename=filename,
        content_type="text/plain",
        size_bytes=size,
        sha256=sha256,
    )
    db.add(artifact)
    db.flush()
    return None, artifact.id


def _upsert_analysis(
    db: Session, project_id: uuid.UUID, run: Run, payload: AnalysisIn
) -> int:
    analysis = db.scalar(select(Analysis).where(Analysis.run_id == run.id))
    if analysis is None:
        analysis = Analysis(
            project_id=project_id,
            run_id=run.id,
            analyzer=payload.analyzer,
            model=payload.model,
            generated_at=payload.generated_at,
            summary=payload.summary,
            payload={},
        )
        db.add(analysis)
    else:
        analysis.analyzer = payload.analyzer
        analysis.model = payload.model
        analysis.generated_at = payload.generated_at
        analysis.summary = payload.summary
    analysis.payload = payload.model_dump(mode="json")

    for item in payload.findings:
        run_case = db.scalar(
            select(RunCase).where(RunCase.run_id == run.id, RunCase.nodeid == item.nodeid)
        )
        if run_case is None:
            raise ApiError(
                422,
                "unknown_nodeid",
                f"finding {item.external_id} 引用了本次运行不存在的 nodeid",
                details={"finding": item.external_id, "nodeid": item.nodeid},
            )
        finding = db.scalar(
            select(Finding).where(
                Finding.project_id == project_id, Finding.external_id == item.external_id
            )
        )
        if finding is None:
            finding = Finding(
                project_id=project_id,
                run_id=run.id,
                run_case_id=run_case.id,
                nodeid=item.nodeid,
                external_id=item.external_id,
                exchange_index=item.exchange_index,
                type=item.type,
                title=item.title,
                summary=item.summary,
                root_cause=item.root_cause,
                impact=item.impact,
                confidence=item.confidence,
                suggested_severity=item.severity,
                requirement_external_id=item.requirement_id,
                status="pending",
            )
            db.add(finding)
        else:
            finding.run_id = run.id
            finding.run_case_id = run_case.id
            finding.nodeid = item.nodeid
            finding.exchange_index = item.exchange_index
            finding.type = item.type
            finding.title = item.title
            finding.summary = item.summary
            finding.root_cause = item.root_cause
            finding.impact = item.impact
            finding.confidence = item.confidence
            finding.suggested_severity = item.severity
            finding.requirement_external_id = item.requirement_id
    return len(payload.findings)
