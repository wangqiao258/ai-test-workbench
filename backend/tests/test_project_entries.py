import pytest
from pydantic import ValidationError

from app.schemas.project import ProjectCreateIn, ProjectEntry


def test_project_entry_normalizes_fields() -> None:
    entry = ProjectEntry(name=" 小程序 ", url=" https://m.example.com/ ")

    assert entry.name == "小程序"
    assert entry.url == "https://m.example.com"
    assert entry.note == ""


def test_project_entry_requires_http_url() -> None:
    with pytest.raises(ValidationError):
        ProjectEntry(name="小程序", url="m.example.com")


def test_project_entries_reject_duplicate_urls() -> None:
    with pytest.raises(ValidationError):
        ProjectCreateIn(
            name="零售系统",
            entries=[
                {"name": "小程序", "url": "https://m.example.com"},
                {"name": "Web", "url": "https://m.example.com/"},
            ],
        )
