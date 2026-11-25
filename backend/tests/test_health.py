from fastapi.testclient import TestClient

from app import __version__
from app.main import app


def test_healthz() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_is_resolved() -> None:
    assert __version__
    assert __version__ != "0.0.0+unknown"
