import base64
import json

from app.services.har import normalized_path, parse_har


def _har(entries: list[dict]) -> bytes:
    return json.dumps({"log": {"version": "1.2", "entries": entries}}).encode("utf-8")


def test_parse_har_keeps_xhr_and_skips_static() -> None:
    entries = [
        {
            "_resourceType": "xhr",
            "time": 31.6,
            "request": {
                "method": "post",
                "url": "https://example.com/api/orders?x=1",
                "headers": [{"name": "Accept", "value": "application/json"}],
                "postData": {"text": '{"sku":"SKU-1"}'},
            },
            "response": {
                "status": 201,
                "headers": [{"name": "Content-Type", "value": "application/json"}],
                "content": {"text": '{"id":"ORD-1"}'},
            },
        },
        {
            "_resourceType": "script",
            "time": 1,
            "request": {"method": "GET", "url": "https://example.com/app.js"},
            "response": {"status": 200},
        },
    ]

    exchanges = parse_har(_har(entries))

    assert len(exchanges) == 1
    exchange = exchanges[0]
    assert exchange.index == 0
    assert exchange.method == "POST"
    assert exchange.status == 201
    assert exchange.request.body == '{"sku":"SKU-1"}'
    assert exchange.response.body == '{"id":"ORD-1"}'
    assert normalized_path(exchange.url) == "/api/orders"


def test_parse_har_decodes_base64_response_body() -> None:
    body = base64.b64encode(b'{"ok":true}').decode("ascii")
    entries = [
        {
            "time": 5,
            "request": {"method": "GET", "url": "https://example.com/api/ping"},
            "response": {
                "status": 200,
                "content": {"text": body, "encoding": "base64"},
            },
        }
    ]

    exchanges = parse_har(_har(entries))

    assert exchanges[0].response.body == '{"ok":true}'


def test_parse_har_rejects_invalid_document() -> None:
    try:
        parse_har(b"not-json")
    except ValueError as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("应当抛出 ValueError")
