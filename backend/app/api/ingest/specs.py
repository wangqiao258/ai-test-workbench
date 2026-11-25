"""AI 机上传 pytest / Tavern YAML 规格，平台机 runner 直接执行。"""

from pathlib import Path

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.core.deps import SCOPE_SPECS_WRITE, require_token_scope
from app.core.errors import ApiError
from app.db.models.project import Project
from app.schemas.specs import SpecUploadIn, SpecUploadOut

router = APIRouter(prefix="/specs", tags=["ingest"])

_ALLOWED_SUFFIXES = {".yaml", ".yml"}


@router.post("", response_model=SpecUploadOut)
def upload_specs(
    payload: SpecUploadIn,
    project: Project = Depends(require_token_scope(SCOPE_SPECS_WRITE)),
) -> SpecUploadOut:
    if not payload.files:
        raise ApiError(422, "empty_specs", "至少上传一个 YAML 文件")

    root = (Path(get_settings().storage_dir) / "specs" / project.key).resolve()
    saved: list[str] = []
    for item in payload.files:
        relative = Path(item.path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ApiError(
                422, "invalid_spec_path", "spec 路径必须是相对路径且不能包含 .."
            )
        if relative.suffix.lower() not in _ALLOWED_SUFFIXES:
            raise ApiError(
                422,
                "invalid_spec_suffix",
                "只接受 .yaml / .yml 文件",
                details={"path": item.path},
            )
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ApiError(422, "invalid_spec_path", "spec 路径超出允许目录")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.content, encoding="utf-8")
        saved.append((Path(project.key) / relative).as_posix())

    return SpecUploadOut(saved=saved, root=str(root))
