from fastapi.testclient import TestClient

from app.main import app
from app.services.agent_views import _safe_headers, _truncate


def test_agent_review_paths_are_read_only_and_token_protected() -> None:
    with TestClient(app) as client:
        spec = client.get("/ingest/openapi.json").json()

    for path in (
        "/ingest/v1/findings",
        "/ingest/v1/findings/{finding_id}",
        "/ingest/v1/defects",
        "/ingest/v1/defects/{defect_id}",
        "/ingest/v1/runs/{run_ref}/cases/{nodeid}",
        "/ingest/v1/runs/{run_ref}/cases/{nodeid}/exchanges/{index}",
    ):
        assert path in spec["paths"]
        assert set(spec["paths"][path]) == {"get"}
        assert spec["paths"][path]["get"].get("security") == [{"ProjectToken": []}]


def test_agent_body_truncation_and_header_redaction() -> None:
    assert _truncate("abcdef", 3) == "abc\n…（已截断，原文 6 字符）"
    headers = _safe_headers(
        [
            {"name": "Authorization", "value": "Bearer secret"},
            {"name": "Accept", "value": "application/json"},
        ]
    )
    assert headers[0] == {"name": "Authorization", "value": "***"}
    assert headers[1] == {"name": "Accept", "value": "application/json"}
