import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.asset import OpenApiDoc, Operation, Requirement
from app.schemas.asset import OpenApiBatchIn, OpenApiIngestOut, RequirementBatchIn
from app.services.operations import rebuild_case_operation_markers


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upsert_requirements(
    db: Session, project_id: uuid.UUID, payload: RequirementBatchIn
) -> int:
    now = _utcnow()
    for item in payload.requirements:
        requirement = db.scalar(
            select(Requirement).where(
                Requirement.project_id == project_id,
                Requirement.external_id == item.external_id,
            )
        )
        if requirement is None:
            requirement = Requirement(project_id=project_id, external_id=item.external_id)
            db.add(requirement)
        requirement.title = item.title
        requirement.version = item.version
        requirement.tags = item.tags
        requirement.owner = item.owner
        requirement.content_md = item.content_md
        requirement.updated_at = item.updated_at or now
    db.flush()
    return len(payload.requirements)


def upsert_openapi(
    db: Session, project_id: uuid.UUID, payload: OpenApiBatchIn
) -> OpenApiIngestOut:
    now = _utcnow()
    operation_count = 0

    for doc_in in payload.docs:
        doc = db.scalar(
            select(OpenApiDoc).where(
                OpenApiDoc.project_id == project_id,
                OpenApiDoc.external_id == doc_in.external_id,
            )
        )
        if doc is None:
            doc = OpenApiDoc(project_id=project_id, external_id=doc_in.external_id)
            db.add(doc)
        doc.title = doc_in.title
        doc.version = doc_in.version
        doc.base_url = doc_in.base_url
        doc.description = doc_in.description
        doc.updated_at = doc_in.updated_at or now
        db.flush()

        existing = {
            operation.external_id: operation
            for operation in db.scalars(
                select(Operation).where(Operation.doc_id == doc.id)
            )
        }
        wanted: set[str] = set()
        for op_in in doc_in.operations:
            wanted.add(op_in.external_id)
            operation = existing.get(op_in.external_id) or db.scalar(
                select(Operation).where(
                    Operation.project_id == project_id,
                    Operation.external_id == op_in.external_id,
                )
            )
            if operation is None:
                operation = Operation(
                    project_id=project_id,
                    external_id=op_in.external_id,
                )
                db.add(operation)
            operation.doc_id = doc.id
            operation.method = op_in.method
            operation.path = op_in.path
            operation.summary = op_in.summary
            operation.tag = op_in.tag
            operation.description = op_in.description
            operation.params = op_in.params
            operation.request_body = op_in.request_body
            operation.responses = op_in.responses
            operation.requirement_external_ids = op_in.requirement_ids
            operation_count += 1

        for external_id, operation in existing.items():
            if external_id not in wanted:
                db.delete(operation)
        db.flush()

    db.flush()
    rebuild_case_operation_markers(db, project_id)
    return OpenApiIngestOut(doc_count=len(payload.docs), operation_count=operation_count)
