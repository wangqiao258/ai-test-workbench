from app.core.access_log import redact_query


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
