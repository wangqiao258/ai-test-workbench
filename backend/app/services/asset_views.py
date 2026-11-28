"""需求 / OpenAPI 的查询视图组装，供查询路由与写入路由复用。"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models.asset import CaseOperationMarker, OpenApiDoc, Operation, Requirement
from app.db.models.case import CaseRequirementMarker, TestCase
from app.schemas.query import (
    OpenApiDocOut,
    OperationOut,
    OperationSummaryListOut,
    OperationSummaryOut,
    RequirementOut,
)


def _requirement_case_map(db: Session, project_id: UUID) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = defaultdict(list)
    rows = db.execute(
        select(CaseRequirementMarker.requirement_external_id, TestCase.nodeid)
        .join(TestCase, TestCase.id == CaseRequirementMarker.case_id)
        .where(CaseRequirementMarker.project_id == project_id)
    ).all()
    for requirement_id, nodeid in rows:
        mapping[requirement_id].append(nodeid)
    return mapping


def _operation_case_map(db: Session, project_id: UUID) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = defaultdict(list)
    rows = db.execute(
        select(CaseOperationMarker.operation_external_id, TestCase.nodeid)
        .join(TestCase, TestCase.id == CaseOperationMarker.case_id)
        .where(CaseOperationMarker.project_id == project_id)
    ).all()
    for operation_id, nodeid in rows:
        mapping[operation_id].append(nodeid)
    return mapping


def _operation_requirement_map(operations: list[Operation]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = defaultdict(list)
    for operation in operations:
        for requirement_id in operation.requirement_external_ids:
            mapping[requirement_id].append(operation.external_id)
    return mapping


def requirement_operation_map(db: Session, project_id: UUID) -> dict[str, list[str]]:
    """需求 -> 接口的关联由用例建立：需求与接口不预先绑定，测过才知道。"""
    mapping: dict[str, set[str]] = defaultdict(set)
    rows = db.execute(
        select(
            CaseRequirementMarker.requirement_external_id,
            CaseOperationMarker.operation_external_id,
        )
        .join(CaseOperationMarker, CaseOperationMarker.case_id == CaseRequirementMarker.case_id)
        .where(
            CaseRequirementMarker.project_id == project_id,
            CaseOperationMarker.project_id == project_id,
        )
        .distinct()
    ).all()
    for requirement_id, operation_id in rows:
        mapping[requirement_id].add(operation_id)
    return {key: sorted(value) for key, value in mapping.items()}


def operation_requirement_map(db: Session, project_id: UUID) -> dict[str, list[str]]:
    """由已测用例反推接口对应的需求，供接口视图展示追溯关系。"""
    mapping: dict[str, set[str]] = defaultdict(set)
    for requirement_id, operation_ids in requirement_operation_map(db, project_id).items():
        for operation_id in operation_ids:
            mapping[operation_id].add(requirement_id)
    return {key: sorted(value) for key, value in mapping.items()}


def requirement_out(
    requirement: Requirement,
    operation_map: dict[str, list[str]],
    case_map: dict[str, list[str]],
    tested_operation_map: dict[str, list[str]],
) -> RequirementOut:
    operation_ids = set(operation_map.get(requirement.external_id, []))
    operation_ids.update(tested_operation_map.get(requirement.external_id, []))
    return RequirementOut(
        id=requirement.external_id,
        title=requirement.title,
        version=requirement.version,
        tags=requirement.tags,
        owner=requirement.owner,
        updated_at=requirement.updated_at,
        content_md=requirement.content_md,
        operation_ids=sorted(operation_ids),
        case_nodeids=sorted(case_map[requirement.external_id]),
    )


def operation_out(
    operation: Operation,
    doc: OpenApiDoc,
    case_map: dict[str, list[str]],
    tested_requirement_map: dict[str, list[str]],
) -> OperationOut:
    requirement_ids = set(operation.requirement_external_ids or [])
    requirement_ids.update(tested_requirement_map.get(operation.external_id, []))
    return OperationOut(
        id=operation.external_id,
        doc_id=doc.external_id,
        method=operation.method,
        path=operation.path,
        summary=operation.summary,
        tag=operation.tag,
        description=operation.description,
        params=operation.params,
        request_body=operation.request_body,
        responses=operation.responses,
        requirement_ids=sorted(requirement_ids),
        case_nodeids=sorted(case_map[operation.external_id]),
    )


def requirement_outs(db: Session, project_id: UUID) -> list[RequirementOut]:
    requirements = list(
        db.scalars(
            select(Requirement)
            .where(Requirement.project_id == project_id)
            .order_by(Requirement.updated_at.desc(), Requirement.external_id)
        )
    )
    operations = list(
        db.scalars(select(Operation).where(Operation.project_id == project_id))
    )
    operation_map = _operation_requirement_map(operations)
    case_map = _requirement_case_map(db, project_id)
    tested_operation_map = requirement_operation_map(db, project_id)
    return [
        requirement_out(item, operation_map, case_map, tested_operation_map)
        for item in requirements
    ]


def requirement_out_one(db: Session, project_id: UUID, requirement: Requirement) -> RequirementOut:
    operations = list(
        db.scalars(select(Operation).where(Operation.project_id == project_id))
    )
    return requirement_out(
        requirement,
        _operation_requirement_map(operations),
        _requirement_case_map(db, project_id),
        requirement_operation_map(db, project_id),
    )


def openapi_doc_outs(db: Session, project_id: UUID) -> list[OpenApiDocOut]:
    docs = list(
        db.scalars(
            select(OpenApiDoc)
            .where(OpenApiDoc.project_id == project_id)
            .order_by(OpenApiDoc.updated_at.desc(), OpenApiDoc.external_id)
        )
    )
    operations = list(
        db.scalars(select(Operation).where(Operation.project_id == project_id))
    )
    case_map = _operation_case_map(db, project_id)
    tested_requirement_map = operation_requirement_map(db, project_id)
    by_doc: dict[UUID, list[Operation]] = defaultdict(list)
    for operation in operations:
        by_doc[operation.doc_id].append(operation)
    return [
        OpenApiDocOut(
            id=doc.external_id,
            title=doc.title,
            version=doc.version,
            base_url=doc.base_url,
            updated_at=doc.updated_at,
            description=doc.description,
            operations=[
                operation_out(item, doc, case_map, tested_requirement_map)
                for item in by_doc[doc.id]
            ],
        )
        for doc in docs
    ]


def operation_out_one(
    db: Session, project_id: UUID, operation: Operation
) -> OperationOut:
    doc = db.get(OpenApiDoc, operation.doc_id)
    return operation_out(
        operation,
        doc,
        _operation_case_map(db, project_id),
        operation_requirement_map(db, project_id),
    )


def openapi_doc_out_one(db: Session, project_id: UUID, doc: OpenApiDoc) -> OpenApiDocOut:
    operations = list(db.scalars(select(Operation).where(Operation.doc_id == doc.id)))
    case_map = _operation_case_map(db, project_id)
    tested_requirement_map = operation_requirement_map(db, project_id)
    return OpenApiDocOut(
        id=doc.external_id,
        title=doc.title,
        version=doc.version,
        base_url=doc.base_url,
        updated_at=doc.updated_at,
        description=doc.description,
        operations=[
            operation_out(item, doc, case_map, tested_requirement_map)
            for item in operations
        ],
    )


def _operation_summary(item: Operation, doc_id: str) -> OperationSummaryOut:
    params = item.params or []
    body = item.request_body or []
    statuses = sorted(
        {
            response.get("status")
            for response in (item.responses or [])
            if isinstance(response.get("status"), int)
        }
    )
    return OperationSummaryOut(
        id=item.external_id,
        doc_id=doc_id,
        method=item.method,
        path=item.path,
        summary=item.summary,
        tag=item.tag,
        description_preview=" ".join((item.description or "").split())[:200],
        required_params=[
            {
                "name": param.get("name", ""),
                "in": param.get("in", ""),
                "type": param.get("type", ""),
            }
            for param in params
            if param.get("required")
        ],
        optional_param_count=sum(1 for param in params if not param.get("required")),
        request_body_fields=[
            {
                "name": field.get("name", ""),
                "type": field.get("type", ""),
                "required": bool(field.get("required")),
            }
            for field in body[:10]
        ],
        request_body_field_count=len(body),
        response_statuses=statuses,
    )


def operations_page(
    db: Session,
    project_id: UUID,
    *,
    tag: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> OperationSummaryListOut:
    conditions = [Operation.project_id == project_id]
    if tag:
        conditions.append(Operation.tag == tag)
    if q:
        like = f"%{q}%"
        conditions.append(
            or_(
                Operation.path.ilike(like),
                Operation.summary.ilike(like),
                Operation.external_id.ilike(like),
            )
        )

    total = db.scalar(select(func.count(Operation.id)).where(*conditions)) or 0
    doc_ids = dict(
        db.execute(
            select(OpenApiDoc.id, OpenApiDoc.external_id).where(
                OpenApiDoc.project_id == project_id
            )
        ).all()
    )
    rows = db.scalars(
        select(Operation)
        .where(*conditions)
        .order_by(Operation.tag, Operation.path, Operation.external_id)
        .offset(offset)
        .limit(limit)
    ).all()
    next_offset = offset + limit if offset + limit < total else None
    return OperationSummaryListOut(
        items=[
            _operation_summary(item, doc_ids.get(item.doc_id, str(item.doc_id)))
            for item in rows
        ],
        total=total,
        next_offset=next_offset,
    )
