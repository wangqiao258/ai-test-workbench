"""需求 / OpenAPI 的查询视图组装，供查询路由与写入路由复用。"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.asset import CaseOperationMarker, OpenApiDoc, Operation, Requirement
from app.db.models.case import CaseRequirementMarker, TestCase
from app.schemas.query import OpenApiDocOut, OperationOut, RequirementOut


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


def requirement_out(
    requirement: Requirement,
    operation_map: dict[str, list[str]],
    case_map: dict[str, list[str]],
) -> RequirementOut:
    return RequirementOut(
        id=requirement.external_id,
        title=requirement.title,
        version=requirement.version,
        tags=requirement.tags,
        owner=requirement.owner,
        updated_at=requirement.updated_at,
        content_md=requirement.content_md,
        operation_ids=sorted(operation_map[requirement.external_id]),
        case_nodeids=sorted(case_map[requirement.external_id]),
    )


def operation_out(
    operation: Operation, doc: OpenApiDoc, case_map: dict[str, list[str]]
) -> OperationOut:
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
        requirement_ids=operation.requirement_external_ids,
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
    return [requirement_out(item, operation_map, case_map) for item in requirements]


def requirement_out_one(db: Session, project_id: UUID, requirement: Requirement) -> RequirementOut:
    operations = list(
        db.scalars(select(Operation).where(Operation.project_id == project_id))
    )
    return requirement_out(
        requirement,
        _operation_requirement_map(operations),
        _requirement_case_map(db, project_id),
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
            operations=[operation_out(item, doc, case_map) for item in by_doc[doc.id]],
        )
        for doc in docs
    ]


def openapi_doc_out_one(db: Session, project_id: UUID, doc: OpenApiDoc) -> OpenApiDocOut:
    operations = list(db.scalars(select(Operation).where(Operation.doc_id == doc.id)))
    case_map = _operation_case_map(db, project_id)
    return OpenApiDocOut(
        id=doc.external_id,
        title=doc.title,
        version=doc.version,
        base_url=doc.base_url,
        updated_at=doc.updated_at,
        description=doc.description,
        operations=[operation_out(item, doc, case_map) for item in operations],
    )
