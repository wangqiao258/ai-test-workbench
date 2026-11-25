from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.case import CaseRequirementMarker


def replace_requirement_markers(
    db: Session,
    project_id: UUID,
    case_id: UUID,
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
