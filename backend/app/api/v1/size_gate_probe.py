"""临时探针：验证体量门禁能拦住新增无人调用端点。验证后立即删除。"""

from fastapi import APIRouter

router = APIRouter(prefix="/projects", tags=["probe"])


@router.get("/{project_id}/size-gate-probe")
def size_gate_probe(project_id: str) -> dict:
    return {"id": project_id}
