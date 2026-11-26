import pytest
from pydantic import ValidationError

from app.schemas.project import AgentRulesIn


def test_agent_rules_trim_and_drop_empty() -> None:
    payload = AgentRulesIn(rules=["  first  ", "", "   ", "second"])
    assert payload.rules == ["first", "second"]


def test_agent_rules_reject_too_long_rule() -> None:
    with pytest.raises(ValidationError):
        AgentRulesIn(rules=["x" * 501])
