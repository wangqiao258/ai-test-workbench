from fastapi import APIRouter

from app.core.deps import SCOPE_CATALOG, TOKEN_PRESETS

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/token-scopes")
def token_scopes() -> dict:
    """scope 与预设有唯一来源，前端不再硬编码。"""
    return {"scopes": list(SCOPE_CATALOG), "presets": list(TOKEN_PRESETS)}
