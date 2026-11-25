import pytest

from app.core.errors import ApiError
from app.services.specs import normalize_spec_path, parse_spec_content


def test_parse_single_tavern_case() -> None:
    cases = parse_spec_content(
        "test_name: 创建订单\n"
        "marks:\n"
        "  - workbench:requirement:A-01\n"
        "  - workbench:tag:smoke\n"
        "stages: []\n"
    )
    assert len(cases) == 1
    assert cases[0].test_name == "创建订单"
    assert cases[0].requirements == ("A-01",)
    assert cases[0].tags == ("smoke",)


def test_parse_multiple_tavern_cases() -> None:
    cases = parse_spec_content(
        "- test_name: 用例一\n  stages: []\n"
        "- test_name: 用例二\n  stages: []\n"
    )
    assert [item.test_name for item in cases] == ["用例一", "用例二"]


def test_parse_ignores_non_test_yaml() -> None:
    assert parse_spec_content("tavern attachment fixture body") == []
    assert parse_spec_content("{\"name\": \"fixture\"}") == []


def test_parse_rejects_duplicate_test_name() -> None:
    with pytest.raises(ApiError):
        parse_spec_content(
            "- test_name: 重复\n  stages: []\n"
            "- test_name: 重复\n  stages: []\n"
        )


def test_parse_rejects_invalid_yaml() -> None:
    with pytest.raises(ApiError):
        parse_spec_content("test_name: [\n")


def test_normalize_spec_path() -> None:
    assert normalize_spec_path("order/create.yaml").as_posix() == "order/create.yaml"
    for value in ("/abs.yaml", "../escape.yaml", "spec.txt", "a\\\\b.yaml"):
        with pytest.raises(ApiError):
            normalize_spec_path(value)
