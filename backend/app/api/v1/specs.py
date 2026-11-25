"""项目规格管理：用例定义的唯一事实源。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_membership, require_role
from app.db.models.identity import ProjectMember
from app.db.session import get_db
from app.schemas.specs import (
    SpecContentIn,
    SpecContentOut,
    SpecDeleteOut,
    SpecFileOut,
    SpecSaveOut,
)
from app.services.audit import record_audit
from app.services.specs import (
    archive_spec_cases,
    delete_spec_file,
    list_spec_files,
    read_spec_file,
    save_spec_content,
    sync_spec_cases,
)

router = APIRouter(prefix="/projects/{project_id}/specs", tags=["specs"])

EDITOR = require_role("admin", "tester", message="当前角色无权修改规格")


@router.get("", response_model=list[SpecFileOut])
def list_specs(
    project_id: UUID,
    _: ProjectMember = Depends(get_membership),
) -> list[SpecFileOut]:
    return [SpecFileOut(**item.__dict__) for item in list_spec_files(project_id)]


@router.get("/content", response_model=SpecContentOut)
def get_spec_content(
    project_id: UUID,
    path: str = Query(min_length=1),
    _: ProjectMember = Depends(get_membership),
) -> SpecContentOut:
    relative, content, sha, updated_at = read_spec_file(project_id, path)
    return SpecContentOut(
        path=relative.as_posix(),
        content=content,
        sha256=sha,
        updated_at=updated_at,
    )


@router.put("/content", response_model=SpecSaveOut)
def save_spec(
    project_id: UUID,
    payload: SpecContentIn,
    member: ProjectMember = Depends(EDITOR),
    db: Session = Depends(get_db),
) -> SpecSaveOut:
    relative, sha, parsed = save_spec_content(
        project_id, payload.path, payload.content, payload.expected_sha256
    )
    case_count, archived_count = sync_spec_cases(db, project_id, relative, parsed)
    record_audit(
        db,
        project_id,
        member.user_id,
        "spec",
        relative.as_posix(),
        "upsert",
        after={
            "sha256": sha,
            "caseCount": case_count,
            "archivedCount": archived_count,
        },
    )
    db.commit()
    return SpecSaveOut(
        path=relative.as_posix(), sha256=sha, case_count=case_count
    )


@router.delete("", response_model=SpecDeleteOut)
def delete_spec(
    project_id: UUID,
    path: str = Query(min_length=1),
    member: ProjectMember = Depends(EDITOR),
    db: Session = Depends(get_db),
) -> SpecDeleteOut:
    relative, file_ref = delete_spec_file(project_id, path)
    archived_count = archive_spec_cases(db, project_id, file_ref)
    record_audit(
        db,
        project_id,
        member.user_id,
        "spec",
        relative.as_posix(),
        "delete",
        after={"archivedCaseCount": archived_count},
    )
    db.commit()
    return SpecDeleteOut(
        path=relative.as_posix(), archived_case_count=archived_count
    )
