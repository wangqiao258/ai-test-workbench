"""从 interfaces 表生成 OpenAPI 3.0 文档（活的 Swagger 文档）。

事实源是 interfaces 表（一接口一记录，带验证状态与证据）；
本模块把项目当前接口快照转成标准 OpenAPI 3.0，供下载或 Swagger UI 渲染。

约定：
- 接口免审（2026-10-22）：全部接口直接进入文档，不再有【待审核】标记。
- 可信度看 x-verify-status：verified / unverified / changed（机器可读）。
- 同一份可信度另在 operation.description 首行给人看：Swagger 折叠时只有 summary，
  展开后第一行就是「可信度：已验证（实测于 …）」，不用去翻 x-* 扩展字段。
- 平台私有信息走扩展字段：x-interface-id / x-verify-status /
  x-verified-at / x-evidence / x-error-codes。
"""
import json

HTTP_METHODS = ("get", "post", "put", "delete", "patch", "head", "options")

# 可信度的中文标签（与网页端同一个口径）。放在 description 首行而不是 summary 前缀：
# 标题前缀会污染接口名（历史上的【待审核】已被废弃），而折叠状态只看得到 summary，
# 展开后第一眼就能读到可信度。
VERIFY_LABEL = {"verified": "已验证", "unverified": "未验证", "changed": "有变更"}


def _verify_line(itf):
    """description 的首行：这条接口的契约可不可信、什么时候实测的。"""
    status = itf.get("verify_status") or "unverified"
    label = VERIFY_LABEL.get(status, status)
    if status == "verified":
        at = (itf.get("verified_at") or "")[:16]
        return f"**可信度：{label}**" + (f"（实测于 {at}）" if at else "")
    if status == "changed":
        return f"**可信度：{label}**（契约改过，证据可能已过期）"
    return f"**可信度：{label}**（契约未经实测，谨慎依赖）"


def _loads(text, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _param_to_openapi(p, location):
    """{name, type, required, desc, example} -> OpenAPI parameter

    容错：元素可以是 dict，也可以是纯字符串（当作 name）。
    """
    if isinstance(p, str):
        p = {"name": p}
    if not isinstance(p, dict):
        return None
    if not p.get("name"):
        return None
    item = {
        "name": p.get("name", ""),
        "in": location,
        "required": bool(p.get("required")) if location != "header" else bool(p.get("required")),
        "description": str(p.get("desc", "")),
        "schema": {"type": str(p.get("type") or "string").lower()},
    }
    if p.get("example") not in (None, ""):
        item["example"] = p["example"]
    return item


def _params_to_openapi(items, location):
    """批量转换并过滤无效项。"""
    out = []
    for p in items or []:
        item = _param_to_openapi(p, location)
        if item:
            out.append(item)
    return out


def _operation(itf):
    """一条接口记录 -> OpenAPI operation 对象"""
    method = (itf.get("method") or "GET").lower()
    if method not in HTTP_METHODS:
        method = "get"

    headers = _loads(itf.get("req_headers"), [])
    params = _loads(itf.get("req_params"), [])

    parameters = _params_to_openapi(headers, "header")

    notes = (itf.get("notes") or "").strip()
    op = {
        "summary": itf.get("name", ""),
        # 首行可信度 + 原始备注：Swagger UI 展开即见，不用翻 x-* 扩展字段
        "description": _verify_line(itf) + (f"\n\n{notes}" if notes else ""),
        "tags": [itf.get("module") or "默认模块"],
        "responses": {},
        # 平台扩展字段
        "x-interface-id": itf.get("id"),
        "x-verify-status": itf.get("verify_status", "unverified"),
        "x-verified-at": itf.get("verified_at", ""),
        "x-evidence": itf.get("evidence", ""),
    }

    # 该接口有独立域名时：用 operation 级 servers 覆盖文档级 servers（OpenAPI 3.0 支持），
    # paths 里始终只放路径，不把域名拼进 path。
    if itf.get("host"):
        op["servers"] = [{"url": itf["host"], "description": "该接口独立域名"}]

    if method in ("get", "delete", "head", "options"):
        parameters += _params_to_openapi(params, "query")
    else:
        # body 参数：组装 requestBody（application/json）
        props, required = {}, []
        for p in params:
            if isinstance(p, str):
                p = {"name": p}
            if not isinstance(p, dict) or not p.get("name"):
                continue
            schema = {"type": (p.get("type") or "string").lower()}
            if p.get("desc"):
                schema["description"] = p["desc"]
            if p.get("example") not in (None, ""):
                schema["example"] = p["example"]
            props[p["name"]] = schema
            if p.get("required"):
                required.append(p["name"])
        if props:
            body_schema = {"type": "object", "properties": props}
            if required:
                body_schema["required"] = required
            op["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": body_schema}},
            }
    if parameters:
        op["parameters"] = parameters

    # 响应示例
    resp_text = itf.get("resp_example") or ""
    resp = {"description": "实测响应示例" if resp_text else "成功"}
    if resp_text:
        parsed = _loads(resp_text, None)
        if parsed is not None:
            resp["content"] = {"application/json": {"example": parsed}}
        else:
            resp["content"] = {"text/plain": {"example": resp_text}}
    op["responses"]["200"] = resp

    error_codes = _loads(itf.get("error_codes"), [])
    if error_codes:
        op["x-error-codes"] = error_codes

    return method, op


def build_openapi(project, envs, interfaces):
    """生成完整 OpenAPI 3.0 文档 dict。

    project: projects 行（dict）；envs: environments 行列表；
    interfaces: interfaces 行列表。
    """
    doc = {
        "openapi": "3.0.3",
        "info": {
            "title": project.get("name", ""),
            "description": (
                "由 AI 协同测试工作台自动维护的活文档：接口经实测提交后即纳入。"
                "扩展字段 x-* 携带验证状态与证据。\n\n"
                + (project.get("description") or "")
            ).strip(),
            "version": "1.0.0",
            "x-generated-at": project.get("generated_at", ""),
        },
        "servers": [
            {"url": e.get("base_url", ""), "description": e.get("name", "")}
            for e in envs if e.get("base_url")
        ],
        "paths": {},
        "tags": [],
    }

    modules = []
    for itf in interfaces:
        method, op = _operation(itf)
        path = itf.get("path") or "/"
        if not path.startswith("/"):
            path = "/" + path
        doc["paths"].setdefault(path, {})[method] = op
        mod = itf.get("module") or "默认模块"
        if mod not in modules:
            modules.append(mod)
    doc["tags"] = [{"name": m} for m in modules]

    # 接口自带独立域名（host 字段）时，补进 servers 列表，避免 Swagger 里看不到可用地址
    known = {s["url"].rstrip("/") for s in doc["servers"] if s.get("url")}
    for itf in interfaces:
        h = (itf.get("host") or "").rstrip("/")
        if h and h not in known:
            known.add(h)
            doc["servers"].append({"url": h, "description": "接口独立域名"})
    return doc
