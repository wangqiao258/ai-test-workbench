from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.ingest import artifacts, assets, assets_read, catalog, docs, jobs, runs, specs, whoami
from app.api.v1 import assets as asset_queries
from app.api.v1 import audit, auth, cases, defects, findings, projects, run_requests
from app.api.v1 import runs as run_queries
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

app.include_router(auth.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(run_requests.router, prefix="/api/v1")
app.include_router(run_queries.router, prefix="/api/v1")
app.include_router(cases.router, prefix="/api/v1")
app.include_router(asset_queries.router, prefix="/api/v1")
app.include_router(findings.router, prefix="/api/v1")
app.include_router(defects.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(whoami.router, prefix="/ingest/v1")
app.include_router(catalog.router, prefix="/ingest/v1")
app.include_router(runs.router, prefix="/ingest/v1")
app.include_router(artifacts.router, prefix="/ingest/v1")
app.include_router(assets.router, prefix="/ingest/v1")
app.include_router(assets_read.router, prefix="/ingest/v1")
app.include_router(specs.router, prefix="/ingest/v1")
app.include_router(jobs.router, prefix="/ingest/v1")
app.include_router(docs.router)


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}
