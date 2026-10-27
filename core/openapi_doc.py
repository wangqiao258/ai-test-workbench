"""由 interfaces 表装配 OpenAPI 文档（网页端与 API 端共用）。"""
from db import get_db, now
from openapi_gen import build_openapi

def _rows(cursor):
    return [dict(r) for r in cursor]

def project_openapi(pid):
    conn = get_db()
    project = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not project:
        conn.close()
        return None
    envs = _rows(conn.execute(
        "SELECT * FROM environments WHERE project_id=?", (pid,)))
    interfaces = _rows(conn.execute(
        "SELECT * FROM interfaces WHERE project_id=? ORDER BY module, path", (pid,)))
    conn.close()
    project = dict(project)
    project["generated_at"] = now()
    return build_openapi(project, envs, interfaces)
