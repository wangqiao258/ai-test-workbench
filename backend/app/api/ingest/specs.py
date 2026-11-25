"""AI 机上传 pytest / Tavern YAML 规格；保存后立即同步用例索引。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import SCOPE_SPECS_WRITE, require_token_scope
from app.core.errors import ApiError
from app.db.models.project import Project
from app.db.session import get_db
from app.schemas.specs import SpecUploadIn, SpecUploadOut
from app.services.specs import (
    normalize_spec_path,
    parse_spec_content,
    project_spec_root,
    save_spec_content,
    sync_spec_cases,
)

router = APIRouter(prefix="/specs", tags=["ingest"])


@router.post("", response_model=SpecUploadOut)
def upload_specs(
    payload: SpecUploadIn,
    project: Project = Depends(require_token_scope(SCOPE_SPECS_WRITE)),
    db: Session = Depends(get_db),
) -> SpecUploadOut:
    if not payload.files:
        raise ApiError(422, "empty_specs", "至少上传一个 YAML 文件")

    for item in payload.files:
        normalize_spec_path(item.path)
        parse_spec_content(item.content)

    saved: list[str] = []
    for item in payload.files:
        relative, _, parsed = save_spec_content(project.id, item.path, item.content)
        sync_spec_cases(db, project.id, relative, parsed)
        saved.append(relative.as_posix())
    db.commit()
    return SpecUploadOut(saved=saved, root=str(project_spec_root(project.id)))
