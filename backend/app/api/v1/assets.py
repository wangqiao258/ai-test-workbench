from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.deps import get_membership
from app.core.errors import ApiError
from app.db.models.asset import CaseOperationMarker, OpenApiDoc, Operation, Requirement
from app.db.models.case import CaseRequirementMarker
from app.db.models.identity import ProjectMember
from app.db.models.review import AuditLog
from app.db.session import get_db
from app.schemas.asset import (
    OpenApiBatchIn,
    OpenApiDocUpdateIn,
    OpenApiImportIn,
    OperationUpdateIn,
    RequirementBatchIn,
    RequirementIn,
    RequirementUpdateIn,
)
from app.schemas.query import OpenApiDocOut, OperationOut, RequirementOut
from app.services.asset_views import (
    openapi_doc_out_one,
    openapi_doc_outs,
    requirement_out_one,
    requirement_outs,
)
from app.services.assets import upsert_openapi, upsert_requirements
from app.services.openapi_import import OpenApiParseError, parse_openapi_document

router = APIRouter(prefix="/projects/{project_id}", tags=["assets"])

_EDITOR_ROLES = {"admin", "tester"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_editor(member: ProjectMember) -> None:
    if member.role not in _EDITOR_ROLES:
        raise ApiError(403, "forbidden", "当前角色无权修改需求与接口资产")


def _audit(
    db: Session,
    project_id: UUID,
    actor_user_id: UUID | None,
    entity_type: str,
    entity_id: str,
    action: str,
    *,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_user_id=actor_user_id,
            before=before,
            after=after,
        )
    )


def _get_requirement(db: Session, project_id: UUID, requirement_id: str) -> Requirement:
    requirement = db.scalar(
        select(Requirement).where(
            Requirement.project_id == project_id,
            Requirement.external_id == requirement_id,
        )
    )
    if requirement is None:
        raise ApiError(404, "requirement_not_found", "需求不存在")
    return requirement


def _get_doc(db: Session, project_id: UUID, doc_id: str) -> OpenApiDoc:
    doc = db.scalar(
        select(OpenApiDoc).where(
            OpenApiDoc.project_id == project_id, OpenApiDoc.external_id == doc_id
        )
    )
    if doc is None:
        raise ApiError(404, "openapi_doc_not_found", "OpenAPI 文档不存在")
    return doc


def _get_operation(db: Session, project_id: UUID, operation_id: str) -> Operation:
    operation = db.scalar(
        select(Operation).where(
            Operation.project_id == project_id, Operation.external_id == operation_id
        )
    )
    if operation is None:
        raise ApiError(404, "operation_not_found", "接口不存在")
    return operation


# ---------- 查询 ----------


@router.get("/requirements", response_model=list[RequirementOut])
def list_requirements(
    project_id: UUID,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[RequirementOut]:
    return requirement_outs(db, project_id)


@router.get("/requirements/{requirement_id}", response_model=RequirementOut)
def get_requirement(
    project_id: UUID,
    requirement_id: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> RequirementOut:
    return requirement_out_one(db, project_id, _get_requirement(db, project_id, requirement_id))


@router.get("/openapi", response_model=list[OpenApiDocOut])
def list_openapi_docs(
    project_id: UUID,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[OpenApiDocOut]:
    return openapi_doc_outs(db, project_id)


@router.get("/openapi/{doc_id}", response_model=OpenApiDocOut)
def get_openapi_doc(
    project_id: UUID,
    doc_id: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> OpenApiDocOut:
    return openapi_doc_out_one(db, project_id, _get_doc(db, project_id, doc_id))


# ---------- 需求写入 ----------


@router.post("/requirements", response_model=RequirementOut)
def upsert_requirement(
    project_id: UUID,
    payload: RequirementIn,
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> RequirementOut:
    _ensure_editor(member)
    upsert_requirements(db, project_id, RequirementBatchIn(requirements=[payload]))
    requirement = _get_requirement(db, project_id, payload.external_id)
    _audit(
        db,
        project_id,
        member.user_id,
        "requirement",
        requirement.external_id,
        "upsert",
        after={"title": requirement.title, "version": requirement.version},
    )
    db.commit()
    db.refresh(requirement)
    return requirement_out_one(db, project_id, requirement)


@router.patch("/requirements/{requirement_id}", response_model=RequirementOut)
def update_requirement(
    project_id: UUID,
    requirement_id: str,
    payload: RequirementUpdateIn,
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> RequirementOut:
    _ensure_editor(member)
    requirement = _get_requirement(db, project_id, requirement_id)
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "title" in updates and not str(updates["title"]).strip():
        raise ApiError(422, "invalid_title", "需求标题不能为空")
    before = {key: getattr(requirement, key) for key in updates}
    for key, value in updates.items():
        setattr(requirement, key, value)
    requirement.updated_at = _utcnow()
    _audit(
        db,
        project_id,
        member.user_id,
        "requirement",
        requirement.external_id,
        "update",
        before=before,
        after=updates,
    )
    db.commit()
    db.refresh(requirement)
    return requirement_out_one(db, project_id, requirement)


@router.delete("/requirements/{requirement_id}", status_code=204)
def delete_requirement(
    project_id: UUID,
    requirement_id: str,
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> None:
    _ensure_editor(member)
    requirement = _get_requirement(db, project_id, requirement_id)
    db.execute(
        delete(CaseRequirementMarker).where(
            CaseRequirementMarker.project_id == project_id,
            CaseRequirementMarker.requirement_external_id == requirement.external_id,
        )
    )
    _audit(
        db,
        project_id,
        member.user_id,
        "requirement",
        requirement.external_id,
        "delete",
        before={"title": requirement.title},
    )
    db.delete(requirement)
    db.commit()


# ---------- OpenAPI 写入 ----------


@router.post("/openapi", response_model=OpenApiDocOut)
def upsert_openapi_doc(
    project_id: UUID,
    payload: OpenApiBatchIn,
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> OpenApiDocOut:
    _ensure_editor(member)
    if not payload.docs:
        raise ApiError(422, "empty_docs", "至少导入一份 OpenAPI 文档")
    result = upsert_openapi(db, project_id, payload)
    last = payload.docs[-1].external_id
    doc = _get_doc(db, project_id, last)
    _audit(
        db,
        project_id,
        member.user_id,
        "openapi_doc",
        doc.external_id,
        "upsert",
        after={"docCount": result.doc_count, "operationCount": result.operation_count},
    )
    db.commit()
    return openapi_doc_out_one(db, project_id, doc)


@router.post("/openapi/import", response_model=OpenApiDocOut)
def import_openapi_doc(
    project_id: UUID,
    payload: OpenApiImportIn,
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> OpenApiDocOut:
    _ensure_editor(member)
    try:
        doc_in = parse_openapi_document(
            payload.content,
            external_id=payload.external_id,
            title=payload.title,
            version=payload.version,
            base_url=payload.base_url,
        )
    except OpenApiParseError as exc:
        raise ApiError(422, "openapi_parse_failed", str(exc)) from exc

    result = upsert_openapi(db, project_id, OpenApiBatchIn(docs=[doc_in]))
    doc = _get_doc(db, project_id, doc_in.external_id)
    _audit(
        db,
        project_id,
        member.user_id,
        "openapi_doc",
        doc.external_id,
        "import",
        after={"operationCount": result.operation_count},
    )
    db.commit()
    return openapi_doc_out_one(db, project_id, doc)


@router.patch("/openapi/operations/{operation_id}", response_model=OperationOut)
def update_operation(
    project_id: UUID,
    operation_id: str,
    payload: OperationUpdateIn,
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> OperationOut:
    _ensure_editor(member)
    operation = _get_operation(db, project_id, operation_id)
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "path" in updates and not str(updates["path"]).strip():
        raise ApiError(422, "invalid_path", "接口 path 不能为空")
    before = {key: getattr(operation, key) for key in updates}
    for key, value in updates.items():
        setattr(operation, key, value)
    operation.updated_at = _utcnow()
    _audit(
        db,
        project_id,
        member.user_id,
        "operation",
        operation.external_id,
        "update",
        before=before,
        after=updates,
    )
    db.commit()
    db.refresh(operation)
    doc = db.get(OpenApiDoc, operation.doc_id)
    if doc is None:
        raise ApiError(404, "openapi_doc_not_found", "OpenAPI 文档不存在")
    return next(
        item
        for item in openapi_doc_out_one(db, project_id, doc).operations
        if item.id == operation.external_id
    )


@router.patch("/openapi/{doc_id}", response_model=OpenApiDocOut)
def update_openapi_doc(
    project_id: UUID,
    doc_id: str,
    payload: OpenApiDocUpdateIn,
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> OpenApiDocOut:
    _ensure_editor(member)
    doc = _get_doc(db, project_id, doc_id)
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "title" in updates and not str(updates["title"]).strip():
        raise ApiError(422, "invalid_title", "文档标题不能为空")
    before = {key: getattr(doc, key) for key in updates}
    for key, value in updates.items():
        setattr(doc, key, value)
    doc.updated_at = _utcnow()
    _audit(
        db,
        project_id,
        member.user_id,
        "openapi_doc",
        doc.external_id,
        "update",
        before=before,
        after=updates,
    )
    db.commit()
    db.refresh(doc)
    return openapi_doc_out_one(db, project_id, doc)


@router.delete("/openapi/{doc_id}", status_code=204)
def delete_openapi_doc(
    project_id: UUID,
    doc_id: str,
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> None:
    _ensure_editor(member)
    doc = _get_doc(db, project_id, doc_id)
    operation_ids = list(
        db.scalars(select(Operation.external_id).where(Operation.doc_id == doc.id))
    )
    if operation_ids:
        db.execute(
            delete(CaseOperationMarker).where(
                CaseOperationMarker.project_id == project_id,
                CaseOperationMarker.operation_external_id.in_(operation_ids),
            )
        )
    _audit(
        db,
        project_id,
        member.user_id,
        "openapi_doc",
        doc.external_id,
        "delete",
        before={"title": doc.title, "operationCount": len(operation_ids)},
    )
    db.delete(doc)
    db.commit()
