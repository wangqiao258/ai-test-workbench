"""AI 机发现项目、目标地址与动作清单。"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.agent_actions import ACTIONS, SCOPE_ANY, WORKFLOW_STEPS
from app.core.agent_rules import DEFAULT_RULES
from app.core.deps import SCOPE_SECRETS_READ, TokenContext, get_token_context
from app.core.time import utcnow
from app.db.models.project import ProjectSecret
from app.db.session import get_db

router = APIRouter(tags=["ingest"])


@router.get("/whoami")
def whoami(
    context: TokenContext = Depends(get_token_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scopes = sorted(context.scopes)
    permitted = [
        action
        for action in ACTIONS
        if action["scope"] == SCOPE_ANY or action["scope"] in context.scopes
    ]
    by_step = {action["step"]: action for action in permitted}
    workflow = [by_step[step] for step in WORKFLOW_STEPS if step in by_step]
    ordered = workflow + [
        action for action in permitted if action["step"] not in WORKFLOW_STEPS
    ]
    actions = [
        {**action, "detail": f"/ingest/v1/actions/{action['step']}"}
        for action in ordered
    ]
    custom_rules = context.project.agent_rules
    rules = list(custom_rules) if custom_rules is not None else list(DEFAULT_RULES)
    secrets: list[dict[str, Any]] = []
    if SCOPE_SECRETS_READ in context.scopes:
        now = utcnow()
        items = db.scalars(
            select(ProjectSecret)
            .where(ProjectSecret.project_id == context.project.id)
            .order_by(ProjectSecret.key)
        ).all()
        secrets = [
            {
                "key": item.key,
                "description": item.description,
                "expiresAt": item.expires_at.isoformat() if item.expires_at else None,
                "expired": item.expires_at is not None and item.expires_at <= now,
            }
            for item in items
        ]
    return {
        "project": {
            "id": str(context.project.id),
            "name": context.project.name,
            "baseUrl": context.project.base_url or None,
            "testRepo": (
                {
                    "url": context.project.test_repo_url,
                    "ref": context.project.test_repo_ref or None,
                }
                if context.project.test_repo_url
                else None
            ),
        },
        "token": {"scopes": scopes},
        "start": workflow[0]["step"] if workflow else None,
        "actions": actions,
        "rules": rules,
        "rulesSource": "custom" if custom_rules is not None else "default",
        "secrets": secrets,
        "docs": {
            "swagger": "/ingest/docs",
            "openapi": "/ingest/openapi.json",
        },
    }
