from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.ingest import actions as ingest_actions
from app.api.ingest import (
    artifacts,
    assets,
    assets_read,
    catalog,
    docs,
    jobs,
    review_read,
    runs,
    specs,
    whoami,
)
from app.api.ingest import operations as ingest_operations
from app.api.ingest import requirements as ingest_requirements
from app.api.ingest import secrets as ingest_secrets
from app.api.v1 import agent_rules as project_agent_rules
from app.api.v1 import assets as asset_queries
from app.api.v1 import audit, auth, cases, defects, findings, meta, projects, tokens
from app.api.v1 import runs as run_queries
from app.api.v1 import secrets as project_secrets
from app.api.v1 import specs as spec_management
from app.core.access_log import AccessLogMiddleware
from app.core.config import get_settings
from app.core.errors import register_exception_handlers

settings = get_settings()

app = FastAPI(title=settings.app_name, version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)
app.add_middleware(AccessLogMiddleware)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(meta.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(project_agent_rules.router, prefix="/api/v1")
app.include_router(tokens.router, prefix="/api/v1")
app.include_router(project_secrets.router, prefix="/api/v1")
app.include_router(run_queries.router, prefix="/api/v1")
app.include_router(cases.router, prefix="/api/v1")
app.include_router(spec_management.router, prefix="/api/v1")
app.include_router(asset_queries.router, prefix="/api/v1")
app.include_router(findings.router, prefix="/api/v1")
app.include_router(defects.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(whoami.router, prefix="/ingest/v1")
app.include_router(review_read.router, prefix="/ingest/v1")
app.include_router(ingest_actions.router, prefix="/ingest/v1")
app.include_router(catalog.router, prefix="/ingest/v1")
app.include_router(runs.router, prefix="/ingest/v1")
app.include_router(artifacts.router, prefix="/ingest/v1")
app.include_router(assets.router, prefix="/ingest/v1")
app.include_router(assets_read.router, prefix="/ingest/v1")
app.include_router(ingest_requirements.router, prefix="/ingest/v1")
app.include_router(ingest_operations.router, prefix="/ingest/v1")
app.include_router(specs.router, prefix="/ingest/v1")
app.include_router(ingest_secrets.router, prefix="/ingest/v1")
app.include_router(jobs.router, prefix="/ingest/v1")
app.include_router(docs.router)


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}
