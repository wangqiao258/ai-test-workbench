from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.access_log import redact_query
from app.core.security import (
    create_ai_ticket,
    decode_access_token,
    decode_ai_ticket,
)
from app.db.models.asset import Operation
from app.main import app
from app.services.review import match_operation_id
from app.services.runs import redact_sensitive_headers, truncate_text


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
    assert truncate_text("abcdef", 3) == "abc\n…（已截断，原文 6 字符）"
    headers = redact_sensitive_headers(
        [
            {"name": "Authorization", "value": "Bearer secret"},
            {"name": "Accept", "value": "application/json"},
        ]
    )
    assert headers[0] == {"name": "Authorization", "value": "***"}
    assert headers[1] == {"name": "Accept", "value": "application/json"}


def test_match_operation_id_uses_method_and_path() -> None:
    operations = [
        Operation(
            external_id="create_meeting_agenda_item",
            method="POST",
            path="/api/v3/meeting_agenda_items",
        ),
        Operation(
            external_id="get_meeting",
            method="GET",
            path="/api/v3/meetings/{id}",
        ),
    ]
    assert (
        match_operation_id(
            operations, "POST", "/api/v3/meeting_agenda_items"
        )
        == "create_meeting_agenda_item"
    )
    assert (
        match_operation_id(operations, "GET", "/api/v3/meetings/42")
        == "get_meeting"
    )
    assert match_operation_id(operations, "GET", "/api/v3/unknown") is None


def test_bundle_schema_exposes_har_and_related_operations() -> None:
    with TestClient(app) as client:
        spec = client.get("/ingest/openapi.json").json()
    properties = spec["components"]["schemas"]["FindingBundleOut"]["properties"]
    assert "har" in properties
    assert "relatedOperations" in properties


def test_ai_ticket_roundtrip_and_scope() -> None:
    project_id = uuid4()
    ticket, expires_at = create_ai_ticket(
        project_id=project_id,
        resource="finding:FND-006",
        run_ref="RUN-MCODE-01",
        nodeid="tests/test_x.py::test_y",
        ttl_minutes=60,
    )
    payload = decode_ai_ticket(ticket)
    assert payload["pid"] == str(project_id)
    assert payload["res"] == "finding:FND-006"
    assert payload["run"] == "RUN-MCODE-01"
    assert payload["node"] == "tests/test_x.py::test_y"
    assert payload["exp"] == int(expires_at.timestamp())


def test_ai_ticket_is_not_a_user_access_token() -> None:
    ticket, _ = create_ai_ticket(
        project_id=uuid4(),
        resource="finding:FND-006",
        run_ref=None,
        nodeid=None,
        ttl_minutes=60,
    )
    with pytest.raises((jwt.PyJWTError, ValueError)):
        decode_access_token(ticket)


def test_ai_ticket_expires() -> None:
    ticket, _ = create_ai_ticket(
        project_id=uuid4(),
        resource="finding:FND-006",
        run_ref=None,
        nodeid=None,
        ttl_minutes=-1,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_ai_ticket(ticket)


def test_ticket_query_is_redacted() -> None:
    assert redact_query([("ticket", "secret-ticket")]) == {
        "ticket": ["***"]
    }


def test_ai_ticket_requires_login() -> None:
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/projects/{uuid4()}/findings/FND-006/ai-ticket"
        )
    assert response.status_code == 401
