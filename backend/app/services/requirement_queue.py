"""按覆盖缺口与风险生成 AI 需求工作队列，避免把全部需求一次塞进上下文。"""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models.asset import Requirement
from app.db.models.case import CaseRequirementMarker, TestCase
from app.schemas.query import RequirementQueueItem, RequirementQueueOut
from app.services.asset_views import requirement_operation_map
from app.services.associations import STATUS_RANK

_STALE_AFTER = timedelta(days=14)


@dataclass
class _Candidate:
    requirement: Requirement
    category: str
    priority: str
    reason: str
    score: int
    case_count: int
    last_status: str | None
    last_run_at: datetime | None
    operation_count: int


def _preview(content: str) -> str:
    text = " ".join((content or "").split())
    return f"{text[:180]}…" if len(text) > 180 else text


def _case_stats(db: Session, project_id: UUID) -> dict[str, dict]:
    rows = db.execute(
        select(
            CaseRequirementMarker.requirement_external_id,
            TestCase.last_status,
            TestCase.last_run_at,
        )
        .join(TestCase, TestCase.id == CaseRequirementMarker.case_id)
        .where(CaseRequirementMarker.project_id == project_id)
    ).all()
    stats: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "worst": None, "last": None}
    )
    for requirement_id, status, last_run_at in rows:
        bucket = stats[requirement_id]
        bucket["count"] += 1
        if status and STATUS_RANK.get(status, 0) > STATUS_RANK.get(bucket["worst"], 0):
            bucket["worst"] = status
        if last_run_at and (bucket["last"] is None or last_run_at > bucket["last"]):
            bucket["last"] = last_run_at
    return stats


def _operation_counts(db: Session, project_id: UUID) -> dict[str, int]:
    return {
        requirement_id: len(operation_ids)
        for requirement_id, operation_ids in requirement_operation_map(
            db, project_id
        ).items()
    }


def _candidate(
    requirement: Requirement,
    stats: dict,
    operation_count: int,
    now: datetime,
) -> _Candidate:
    case_count = stats["count"]
    last_status = stats["worst"]
    last_run_at = stats["last"]

    if case_count == 0:
        priority, reason, score = "high", "未被用例覆盖", 100
    elif last_status in ("failed", "error"):
        priority, reason, score = "high", "最近运行失败", 80
    elif last_run_at is None:
        priority, reason, score = "medium", "关联用例从未运行", 60
    elif now - last_run_at > _STALE_AFTER:
        priority, reason, score = "medium", "覆盖已超过 14 天", 40
    elif requirement.updated_at > last_run_at:
        priority, reason, score = "medium", "需求在最近运行后更新", 30
    else:
        priority, reason, score = "low", "常规覆盖", 10

    score += max(0, 5 - min(case_count, 5))
    score += min(operation_count, 10)
    tags = list(requirement.tags or [])
    return _Candidate(
        requirement=requirement,
        category=tags[0] if tags else "未分类",
        priority=priority,
        reason=reason,
        score=score,
        case_count=case_count,
        last_status=last_status,
        last_run_at=last_run_at,
        operation_count=operation_count,
    )


def _interleave(candidates: list[_Candidate]) -> list[_Candidate]:
    """按分类轮转，避免一页里全是同一模块的需求。"""
    buckets: dict[str, deque[_Candidate]] = {}
    for candidate in candidates:
        buckets.setdefault(candidate.category, deque()).append(candidate)
    categories = list(buckets)
    ordered: list[_Candidate] = []
    while True:
        added = False
        for category in categories:
            bucket = buckets[category]
            if bucket:
                ordered.append(bucket.popleft())
                added = True
        if not added:
            return ordered


def build_requirement_queue(
    db: Session,
    project_id: UUID,
    *,
    limit: int,
    offset: int,
    tag: str | None,
) -> RequirementQueueOut:
    requirements = list(
        db.scalars(select(Requirement).where(Requirement.project_id == project_id))
    )
    if tag:
        requirements = [
            item for item in requirements if tag in (item.tags or [])
        ]

    case_stats = _case_stats(db, project_id)
    operation_counts = _operation_counts(db, project_id)
    now = utcnow()
    candidates = [
        _candidate(
            item,
            case_stats.get(item.external_id, {"count": 0, "worst": None, "last": None}),
            operation_counts.get(item.external_id, 0),
            now,
        )
        for item in requirements
    ]
    candidates.sort(
        key=lambda item: (
            -item.score,
            -item.requirement.updated_at.timestamp(),
            item.requirement.external_id,
        )
    )
    ordered = _interleave(candidates)
    page = ordered[offset : offset + limit]
    next_offset = offset + limit if offset + limit < len(ordered) else None

    return RequirementQueueOut(
        items=[
            RequirementQueueItem(
                id=item.requirement.external_id,
                title=item.requirement.title,
                category=item.category,
                tags=list(item.requirement.tags or []),
                priority=item.priority,
                reason=item.reason,
                updated_at=item.requirement.updated_at,
                case_count=item.case_count,
                last_status=item.last_status,
                last_run_at=item.last_run_at,
                operation_count=item.operation_count,
                preview=_preview(item.requirement.content_md),
            )
            for item in page
        ],
        total=len(ordered),
        next_offset=next_offset,
    )
