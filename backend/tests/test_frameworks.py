import pytest
from pydantic import ValidationError

from app.schemas.ingest import CaseIn, CatalogCaseIn, CatalogIn


def test_catalog_case_defaults_to_pytest() -> None:
    case = CatalogCaseIn(nodeid="tests/test_order.py::test_create")
    assert case.framework == "pytest"


def test_catalog_case_normalizes_framework() -> None:
    case = CatalogCaseIn(nodeid="e2e/order.spec.ts::create", framework="Playwright")
    assert case.framework == "playwright"


def test_catalog_case_accepts_any_framework() -> None:
    case = CatalogCaseIn(nodeid="tests/test_order.py::test_create", framework="Selenium")
    assert case.framework == "selenium"


def test_catalog_case_rejects_script() -> None:
    with pytest.raises(ValidationError):
        CatalogCaseIn(nodeid="scripts/check.sh::smoke", framework="script")


def test_run_case_accepts_script() -> None:
    case = CaseIn(nodeid="scripts/check.sh::smoke", status="passed", framework="script")
    assert case.framework == "script"


def test_run_case_accepts_arbitrary_framework() -> None:
    case = CaseIn(nodeid="scripts/check.sh::smoke", status="passed", framework="Bash")
    assert case.framework == "bash"


def test_catalog_source_is_trimmed() -> None:
    payload = CatalogIn(
        source={"repo": " git@example.com:team/tests.git ", "ref": " main ", "commit": " abc "},
        cases=[],
    )
    assert payload.source is not None
    assert payload.source.repo == "git@example.com:team/tests.git"
    assert payload.source.ref == "main"
    assert payload.source.commit == "abc"
