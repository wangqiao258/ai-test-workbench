"""把原始 OpenAPI 3.x 文档解析成平台内部的接口契约结构。

供前端「导入 OpenAPI」使用。只做结构化提取，不执行任何外部请求。
"""

from __future__ import annotations

from typing import Any

import yaml

from app.schemas.asset import OpenApiDocIn, OperationIn

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


class OpenApiParseError(ValueError):
    """原始文档无法解析为可入库的契约。"""


def parse_openapi_document(
    content: str,
    *,
    external_id: str,
    title: str = "",
    version: str = "",
    base_url: str = "",
) -> OpenApiDocIn:
    document = _load_document(content)
    info = document.get("info") if isinstance(document.get("info"), dict) else {}
    paths = document.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise OpenApiParseError("文档不包含 paths，没有可导入的接口")

    operations: list[OperationIn] = []
    used_ids: set[str] = set()
    for path, path_item in paths.items():
        path_item = _resolve(document, path_item)
        if not isinstance(path_item, dict):
            continue
        for method, raw_operation in path_item.items():
            if method.lower() not in _HTTP_METHODS:
                continue
            operation = _resolve(document, raw_operation)
            if not isinstance(operation, dict):
                continue
            operation_id = str(
                operation.get("operationId") or f"{method.upper()} {path}"
            )
            operation_id = _unique(operation_id, used_ids)
            operations.append(
                OperationIn(
                    external_id=operation_id,
                    method=method.upper(),
                    path=str(path),
                    summary=_text(operation.get("summary")),
                    tag=_first_tag(operation),
                    description=_text(operation.get("description")),
                    params=_params(document, operation),
                    request_body=_request_body(document, operation),
                    responses=_responses(document, operation),
                    requirement_ids=_requirement_ids(operation),
                )
            )

    return OpenApiDocIn(
        external_id=external_id,
        title=title or _text(info.get("title")) or external_id,
        version=version or _text(info.get("version")),
        base_url=base_url or _server_url(document),
        description=_text(info.get("description")),
        operations=operations,
    )


def _load_document(content: str) -> dict[str, Any]:
    try:
        # yaml.safe_load 同时兼容 JSON 与 YAML 文本。
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise OpenApiParseError(f"JSON / YAML 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise OpenApiParseError("文档根节点必须是对象")
    if "swagger" in data and "openapi" not in data:
        raise OpenApiParseError("暂不支持 Swagger 2.0，请先转换为 OpenAPI 3.x")
    if "openapi" not in data:
        raise OpenApiParseError("缺少 openapi 版本字段，无法识别为 OpenAPI 3.x 文档")
    return data


def _resolve(spec: dict[str, Any], node: Any, depth: int = 0) -> dict[str, Any]:
    if not isinstance(node, dict):
        return {}
    if depth > 5:
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        current: Any = spec
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(current, dict) or part not in current:
                return node
            current = current[part]
        return _resolve(spec, current, depth + 1)
    return node


def _type_name(schema: dict[str, Any]) -> str:
    if not schema:
        return "any"
    raw_type = schema.get("type")
    if isinstance(raw_type, list):
        return "|".join(str(item) for item in raw_type)
    if raw_type == "array":
        return f"array<{_type_name(_resolve(schema, schema.get('items') or {}))}>"
    if raw_type:
        return str(raw_type)
    if "oneOf" in schema or "anyOf" in schema:
        return "oneOf"
    if schema.get("properties"):
        return "object"
    if schema.get("enum"):
        return "enum"
    return "any"


def _schema_fields(
    spec: dict[str, Any], schema: Any, depth: int = 0
) -> list[dict[str, Any]]:
    schema = _resolve(spec, schema, depth)
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    required = set(schema.get("required") or [])
    fields: list[dict[str, Any]] = []
    for name, raw in properties.items():
        prop = _resolve(spec, raw, depth)
        fields.append(
            {
                "name": str(name),
                "type": _type_name(prop),
                "required": name in required,
                "description": _text(prop.get("description")),
            }
        )
    return fields


def _params(spec: dict[str, Any], operation: dict[str, Any]) -> list[dict[str, Any]]:
    params: list[dict[str, Any]] = []
    raw_params = operation.get("parameters")
    if not isinstance(raw_params, list):
        return params
    for raw in raw_params:
        param = _resolve(spec, raw)
        name = param.get("name")
        if not name:
            continue
        schema = _resolve(spec, param.get("schema") or {})
        params.append(
            {
                "name": str(name),
                "in": str(param.get("in") or "query"),
                "type": _type_name(schema),
                "required": bool(param.get("required")),
                "description": _text(param.get("description")),
            }
        )
    return params


def _request_body(
    spec: dict[str, Any], operation: dict[str, Any]
) -> list[dict[str, Any]] | None:
    body = _resolve(spec, operation.get("requestBody") or {})
    content = body.get("content")
    if not isinstance(content, dict) or not content:
        return None
    media = content.get("application/json")
    if not isinstance(media, dict):
        media = next((item for item in content.values() if isinstance(item, dict)), {})
    schema = _resolve(spec, media.get("schema") or {})
    fields = _schema_fields(spec, schema)
    return fields or None


def _responses(
    spec: dict[str, Any], operation: dict[str, Any]
) -> list[dict[str, Any]]:
    raw_responses = operation.get("responses")
    if not isinstance(raw_responses, dict):
        return []
    responses: list[dict[str, Any]] = []
    for code, raw in raw_responses.items():
        response = _resolve(spec, raw)
        try:
            status = int(code)
        except (TypeError, ValueError):
            status = 0
        content = response.get("content")
        media = (
            content.get("application/json")
            if isinstance(content, dict) and isinstance(content.get("application/json"), dict)
            else {}
        )
        schema = _resolve(spec, media.get("schema") or {})
        responses.append(
            {
                "status": status,
                "description": _text(response.get("description"))
                or ("默认响应" if status == 0 else ""),
                "fields": _schema_fields(spec, schema),
            }
        )
    responses.sort(key=lambda item: (item["status"] == 0, item["status"]))
    return responses


def _requirement_ids(operation: dict[str, Any]) -> list[str]:
    raw = operation.get("x-requirement-ids")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def _server_url(document: dict[str, Any]) -> str:
    servers = document.get("servers")
    if isinstance(servers, list):
        for server in servers:
            if isinstance(server, dict) and server.get("url"):
                return str(server["url"])
    return ""


def _first_tag(operation: dict[str, Any]) -> str:
    tags = operation.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if str(tag).strip():
                return str(tag)
    return ""


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _unique(candidate: str, used: set[str]) -> str:
    if candidate not in used:
        used.add(candidate)
        return candidate
    index = 2
    while f"{candidate}~{index}" in used:
        index += 1
    result = f"{candidate}~{index}"
    used.add(result)
    return result
