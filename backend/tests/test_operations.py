from app.services.operations import compile_path


def test_compile_path_matches_static_path() -> None:
    pattern = compile_path("/v1/orders")
    assert pattern.fullmatch("/v1/orders")
    assert not pattern.fullmatch("/v1/orders/123")


def test_compile_path_matches_placeholder_segment() -> None:
    pattern = compile_path("/v1/orders/{orderId}")
    assert pattern.fullmatch("/v1/orders/ORD-1")
    assert not pattern.fullmatch("/v1/orders/ORD-1/items")


def test_compile_path_escapes_regex_characters() -> None:
    pattern = compile_path("/v1/orders/{orderId}/items.json")
    assert pattern.fullmatch("/v1/orders/ORD-1/items.json")
    assert not pattern.fullmatch("/v1/orders/ORD-1/itemsxjson")
