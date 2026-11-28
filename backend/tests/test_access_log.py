from fastapi.testclient import TestClient

from app.core.access_log import redact_query
from app.main import app
from scripts.manage import DEPRECATED_ROUTES


def test_redact_query_masks_sensitive_values() -> None:
    result = redact_query(
        [("token", "abc"), ("page", "1"), ("access_token", "xyz"), ("name", "demo")]
    )
    assert result["token"] == ["***"]
    assert result["access_token"] == ["***"]
    assert result["page"] == ["1"]
    assert result["name"] == ["demo"]


def test_redact_query_keeps_repeated_keys() -> None:
    result = redact_query([("tag", "a"), ("tag", "b")])
    assert result["tag"] == ["a", "b"]


def test_deprecated_endpoints_are_marked_in_openapi() -> None:
    with TestClient(app) as client:
        spec = client.get("/openapi.json").json()
    for method, route in DEPRECATED_ROUTES:
        operation = spec["paths"][f"/api/v1{route}"][method.lower()]
        assert operation["deprecated"] is True
