"""HAR 解析与有效性判定。

有效 HAR 需满足：
- 合法 JSON，且 ``log.entries`` 为数组；
- 至少有一条 http(s) 且带 host 的 XHR / Fetch 请求（未标注 ``_resourceType`` 的也接受）；
- 标注为 document / script / stylesheet / image 等静态资源的条目不计入证据。
"""

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

    log = document.get("log")
    entries = log.get("entries") if isinstance(log, dict) else None
    if not isinstance(entries, list):
        raise ValueError("HAR 缺少 log.entries 数组")

    exchanges: list[ExchangeIn] = []
    for entry in entries:
        if not isinstance(entry, dict) or not _is_api_entry(entry):
            continue
        exchanges.append(_to_exchange(entry, index=len(exchanges)))
    if not exchanges:
        raise ValueError("HAR 中没有可用的接口请求：需要包含 http(s) 的 XHR/Fetch 记录")
    return exchanges


def _is_api_entry(entry: dict[str, Any]) -> bool:
    resource_type = entry.get("_resourceType")
    if resource_type not in (None, "xhr", "fetch"):
        return False
    request = entry.get("request")
    url = str(request.get("url") or "") if isinstance(request, dict) else ""
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


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
