from fastapi.testclient import TestClient

from app.main import app


def test_filtered_ingest_spec_only_contains_ingest_paths() -> None:
    with TestClient(app) as client:
        response = client.get("/ingest/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert spec["paths"]
    assert all(path.startswith("/ingest/") for path in spec["paths"])
    assert "/api/v1/projects" not in spec["paths"]
    scheme = spec["components"]["securitySchemes"]["ProjectToken"]
    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "header"
    assert scheme["name"] == "X-Project-Token"


def test_ingest_routes_declare_project_token_security() -> None:
    with TestClient(app) as client:
        spec = client.get("/ingest/openapi.json").json()
    security = spec["paths"]["/ingest/v1/specs"]["post"].get("security")
    assert security == [{"ProjectToken": []}]


def test_ingest_spec_carries_examples() -> None:
    with TestClient(app) as client:
        spec = client.get("/ingest/openapi.json").json()
    schemas = spec["components"]["schemas"]
    assert schemas["SpecUploadIn"]["examples"]
    assert schemas["AnalysisIn"]["examples"]


def test_ingest_swagger_page() -> None:
    with TestClient(app) as client:
        response = client.get("/ingest/docs")
    assert response.status_code == 200
    assert "/ingest/openapi.json" in response.text
