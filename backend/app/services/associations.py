"""已测关联：需求与接口的对应关系由真实测试请求积累，测得多置信度越高。"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.asset import CaseOperationMarker, Operation
from app.db.models.case import CaseRequirementMarker, TestCase
from app.schemas.query import RequirementAssociationsOut, RequirementOperationOut

STATUS_RANK = {"error": 4, "failed": 3, "skipped": 2, "passed": 1}


def _confidence(case_count: int) -> str:
    if case_count >= 3:
        return "high"
    if case_count == 2:
        return "medium"
    return "low"


def requirement_associations(
    db: Session,
    project_id: UUID,
    requirement_id: str,
    *,
    limit: int,
) -> RequirementAssociationsOut:
    rows = db.execute(
        select(
            CaseOperationMarker.operation_external_id,
            CaseRequirementMarker.case_id,
            TestCase.last_status,
            TestCase.last_run_at,
        )
        .join(
            CaseRequirementMarker,
            CaseRequirementMarker.case_id == CaseOperationMarker.case_id,
        )
        .join(TestCase, TestCase.id == CaseOperationMarker.case_id)
        .where(
            CaseRequirementMarker.project_id == project_id,
            CaseRequirementMarker.requirement_external_id == requirement_id,
            CaseOperationMarker.project_id == project_id,
        )
    ).all()

    stats: dict[str, dict] = defaultdict(
        lambda: {"cases": set(), "worst": None, "last": None}
    )
    for operation_id, case_id, status, last_run_at in rows:
        bucket = stats[operation_id]
        bucket["cases"].add(case_id)
        if status and STATUS_RANK.get(status, 0) > STATUS_RANK.get(bucket["worst"], 0):
            bucket["worst"] = status
        if last_run_at and (bucket["last"] is None or last_run_at > bucket["last"]):
            bucket["last"] = last_run_at

    if not stats:
        return RequirementAssociationsOut(
            requirement_id=requirement_id, operations=[], total=0
        )

    operations = {
        item.external_id: item
        for item in db.scalars(
            select(Operation).where(
                Operation.project_id == project_id,
                Operation.external_id.in_(list(stats)),
            )
        )
    }
    items: list[RequirementOperationOut] = []
    for operation_id, bucket in stats.items():
        operation = operations.get(operation_id)
        if operation is None:
            continue
        case_count = len(bucket["cases"])
        items.append(
            RequirementOperationOut(
                id=operation.external_id,
                method=operation.method,
                path=operation.path,
                summary=operation.summary,
                tag=operation.tag,
                case_count=case_count,
                last_status=bucket["worst"],
                last_run_at=bucket["last"],
                confidence=_confidence(case_count),
            )
        )
    items.sort(key=lambda item: (-item.case_count, item.path, item.id))
    return RequirementAssociationsOut(
        requirement_id=requirement_id,
        operations=items[:limit],
        total=len(items),
    )
