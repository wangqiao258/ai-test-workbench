import base64
import json
from typing import Any
from urllib.parse import urlparse

from app.schemas.ingest import ExchangeIn, HeaderItem, HttpPayload


def parse_har(data: bytes) -> list[ExchangeIn]:
    try:
        document = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"HAR 不是合法 JSON：{exc.msg}") from exc

    entries = document.get("log", {}).get("entries")
    if not isinstance(entries, list):
        raise ValueError("HAR 缺少 log.entries 数组")

    exchanges: list[ExchangeIn] = []
    for entry in entries:
        if not isinstance(entry, dict) or not _is_api_entry(entry):
            continue
        exchanges.append(_to_exchange(entry, index=len(exchanges)))
    return exchanges


def _is_api_entry(entry: dict[str, Any]) -> bool:
    resource_type = entry.get("_resourceType")
    return resource_type in (None, "xhr", "fetch")


def _to_exchange(entry: dict[str, Any], index: int) -> ExchangeIn:
    request = entry.get("request") or {}
    response = entry.get("response") or {}
    url = str(request.get("url") or "")
    return ExchangeIn(
        index=index,
        method=str(request.get("method") or "GET").upper(),
        url=url,
        status=response.get("status"),
        elapsed_ms=int(entry.get("time") or 0),
        request=HttpPayload(
            headers=_headers(request.get("headers")),
            body=_text(request.get("postData", {}).get("text")),
        ),
        response=HttpPayload(
            headers=_headers(response.get("headers")),
            body=_response_body(response.get("content") or {}),
        ),
        error=entry.get("_error") or None,
    )


def _headers(raw: Any) -> list[HeaderItem]:
    if not isinstance(raw, list):
        return []
    return [
        HeaderItem(name=str(item.get("name") or ""), value=str(item.get("value") or ""))
        for item in raw
        if isinstance(item, dict) and item.get("name")
    ]


def _response_body(content: dict[str, Any]) -> str | None:
    text = content.get("text")
    if not isinstance(text, str):
        return None
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(text).decode("utf-8", errors="replace")
        except (ValueError, TypeError):
            return text
    return text


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def normalized_path(url: str) -> str:
    return urlparse(url).path or "/"
