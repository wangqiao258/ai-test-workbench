import re
import uuid
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.asset import CaseOperationMarker, Operation
from app.db.models.case import CaseRequirementMarker, TestCase
from app.db.models.run import Exchange, RunCase

_PLACEHOLDER = re.compile(r"(\{[^}]+\})")


def compile_path(template: str) -> re.Pattern[str]:
    """把 OpenAPI 路径模板编译成匹配实际请求路径的正则，例如 /v1/orders/{id}。"""
    parts = _PLACEHOLDER.split(template)
    regex = "".join(
        "[^/]+" if part.startswith("{") and part.endswith("}") else re.escape(part)
        for part in parts
    )
    return re.compile(rf"^{regex}$")


def rebuild_case_operation_markers(
    db: Session, project_id: uuid.UUID, case_ids: list[uuid.UUID] | None = None
) -> int:
    """按用例最近一次运行的实际请求 method + path 重建 operation 关联。"""
    operations = list(db.scalars(select(Operation).where(Operation.project_id == project_id)))
    compiled = [
        (operation.external_id, operation.method.upper(), compile_path(operation.path))
        for operation in operations
    ]

    stmt = select(TestCase).where(TestCase.project_id == project_id)
    if case_ids is not None:
        stmt = stmt.where(TestCase.id.in_(case_ids))
    cases = list(db.scalars(stmt))
    if not cases:
        return 0

    db.execute(
        delete(CaseOperationMarker).where(
            CaseOperationMarker.case_id.in_([case.id for case in cases]),
            CaseOperationMarker.source == "auto",
        )
    )

    latest_run = {case.id: case.last_run_id for case in cases if case.last_run_id is not None}
    paths_by_case: dict[uuid.UUID, set[tuple[str, str]]] = defaultdict(set)
    if latest_run:
        rows = db.execute(
            select(RunCase.case_id, RunCase.run_id, Exchange.method, Exchange.path_norm)
            .join(Exchange, Exchange.run_case_id == RunCase.id)
            .where(RunCase.run_id.in_(set(latest_run.values())))
        ).all()
        for case_id, run_id, method, path in rows:
            if latest_run.get(case_id) == run_id:
                paths_by_case[case_id].add((method.upper(), path))

    marker_count = 0
    for case_id, exchanges in paths_by_case.items():
        matched: set[str] = set()
        for method, path in exchanges:
            for external_id, operation_method, pattern in compiled:
                if method == operation_method and pattern.fullmatch(path):
                    matched.add(external_id)
        for external_id in sorted(matched):
            db.add(
                CaseOperationMarker(
                    project_id=project_id,
                    case_id=case_id,
                    operation_external_id=external_id,
                    source="auto",
                )
            )
            marker_count += 1
    db.flush()
    return marker_count


def replace_requirement_markers(
    db: Session,
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    requirements: list[str],
) -> int:
    """用用例上的 requirement marks 覆盖 marker 来源的关联，保留人工关联。"""
    wanted = [item.strip() for item in requirements if item.strip()]
    wanted_set = set(wanted)
    existing = {
        marker.requirement_external_id: marker
        for marker in db.scalars(
            select(CaseRequirementMarker).where(CaseRequirementMarker.case_id == case_id)
        )
    }
    for requirement_id in dict.fromkeys(wanted):
        if requirement_id not in existing:
            db.add(
                CaseRequirementMarker(
                    project_id=project_id,
                    case_id=case_id,
                    requirement_external_id=requirement_id,
                    source="marker",
                )
            )
    for requirement_id, marker in existing.items():
        if marker.source == "marker" and requirement_id not in wanted_set:
            db.delete(marker)
    return len(wanted_set)
