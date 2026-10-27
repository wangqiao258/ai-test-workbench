"""数据包证据：请求/响应报文的校验、完整度判定与落盘策略。

起因（2026-10-22 核实）：页面标题写着「验证证据（真实数据包）」，
实际 161 条接口里只有 22% 含请求行+状态码+响应体，最短的一条是 10 个字符
`GET -> 200`；而它照样拿到了 verify_status=verified。原因是判定只有
`bool(evidence.strip())`——非空即"已实测"。

这里的规则把"完整的数据包"变成可判定的事：
1. 请求与响应的每一部分单独成列，不再塞进一个自由文本框；
2. 完整度由服务端算（completeness），不信任调用方自报；
3. 响应体超过阈值就落盘到 data/uploads/packets/，DB 只存引用——
   **永不截断**（旧数据里已有 20000 字符被切在半个 JSON 中间的先例）。

纯逻辑，不 import flask/db，便于单测。
"""
import hashlib
import json
from urllib.parse import urlencode, urlsplit

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")

# 数据包可以挂在哪些对象上（白名单，防拼进 SQL/路径）
LINKED_TYPES = ("interface", "bug", "execution")

# 响应体超过这个字符数就落盘。8KB 足够覆盖绝大多数正常接口，
# 而字典/列表这类全量返回（实测 11 万字符）必须落盘，否则又会滑向截断。
INLINE_CHARS = 8192

# 这些情况下响应体空是合法的，不算"缺响应体"
NO_BODY_STATUS = (204, 304)
NO_BODY_METHODS = ("HEAD",)

# 完整度词表
FULL, PARTIAL = "full", "partial"


def _as_text(v):
    """把 body/headers 这类字段统一成字符串。list/dict 按 JSON 存，保留结构。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def _as_headers(v):
    """请求头/响应头统一成 {name: value} 的 JSON 文本。

    接受三种写法：dict、[[k, v], ...]（浏览器开发者工具导出常见）、已是 JSON 字符串。
    """
    if not v:
        return ""
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return ""
        try:
            return json.dumps(json.loads(s), ensure_ascii=False)
        except Exception:
            # 不是 JSON 就按 "Key: Value" 逐行解析，解析不了就原样保留
            out = {}
            for line in s.splitlines():
                if ":" in line:
                    k, _, val = line.partition(":")
                    if k.strip():
                        out[k.strip()] = val.strip()
            return json.dumps(out, ensure_ascii=False) if out else json.dumps({"raw": s},
                                                                             ensure_ascii=False)
    if isinstance(v, dict):
        return json.dumps({str(k): _as_text(val) for k, val in v.items()}, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        out = {}
        for item in v:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                out[str(item[0])] = _as_text(item[1])
            elif isinstance(item, dict) and item.get("name"):
                out[str(item["name"])] = _as_text(item.get("value", ""))
        return json.dumps(out, ensure_ascii=False)
    return json.dumps({"raw": _as_text(v)}, ensure_ascii=False)


def _as_int(v, default=None):
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def normalize(data):
    """把请求体里的数据包规整成入库形状。

    返回 (norm, err)。err 非空即拒绝——拒的是"根本不成形的报文"，
    不是"完整的报文"，后者交给 completeness 判级。
    """
    if not isinstance(data, dict):
        return None, "请求体必须是 JSON 对象"

    linked_type = (data.get("linked_type") or "").strip()
    if linked_type not in LINKED_TYPES:
        return None, f"linked_type 必须是 {list(LINKED_TYPES)} 之一"

    linked_id = _as_int(data.get("linked_id"))
    if not linked_id:
        return None, "linked_id 必填（挂在哪个对象上）"

    project_id = _as_int(data.get("project_id"))
    if not project_id:
        return None, "project_id 必填"

    req = data.get("request") or {}
    resp = data.get("response") or {}
    if not isinstance(req, dict) or not isinstance(resp, dict):
        return None, "request / response 必须是对象"

    method = (req.get("method") or "").strip().upper()
    if method not in METHODS:
        return None, f"request.method 必须是 {list(METHODS)} 之一"

    url = (req.get("url") or "").strip()
    if not url:
        return None, "request.url 必填（完整地址或 / 开头的路径）"
    if not (url.startswith(("http://", "https://", "/"))):
        return None, "request.url 需为 http(s):// 绝对地址，或以 / 开头的路径"

    status = _as_int(resp.get("status"))
    if status is None:
        return None, "response.status 必填且为整数（100-599）"
    if not 100 <= status <= 599:
        return None, "response.status 需在 100-599 之间"

    resp_body = _as_text(resp.get("body"))
    req_body = _as_text(req.get("body"))
    resp_headers = _as_headers(resp.get("headers"))
    req_headers = _as_headers(req.get("headers"))

    norm = {
        "project_id": project_id,
        "linked_type": linked_type,
        "linked_id": linked_id,
        "label": (data.get("label") or "").strip(),
        "req_method": method,
        "req_url": url,
        "req_query": _as_text(req.get("query")) if isinstance(req.get("query"), (dict, list))
        else (req.get("query") or ""),
        "req_headers": req_headers,
        "req_body": req_body,
        "resp_status": status,
        "resp_headers": resp_headers,
        "resp_body": resp_body,
        "duration_ms": _as_int(resp.get("duration_ms")),
        "captured_at": (data.get("captured_at") or "").strip(),
    }
    # 空的 query 统一存空串，避免 "{}" 这种噪音
    if not norm["req_query"]:
        norm["req_query"] = ""
    return norm, None


def completeness(norm):
    """判完整度，返回 (level, missing_text)。

    必需的只有四样：请求方法、请求地址、响应状态码、响应体（无体场景除外）。
    请求头/响应头缺失只记提示，不降级——没头的包依然能复核返回内容。
    """
    missing = []
    if not norm.get("req_method") or not norm.get("req_url"):
        missing.append("请求行")
    if norm.get("resp_status") is None:
        missing.append("响应状态码")

    method = (norm.get("req_method") or "").upper()
    status = norm.get("resp_status")
    body_allowed_empty = method in NO_BODY_METHODS or status in NO_BODY_STATUS
    if not (norm.get("resp_body") or "").strip() and not body_allowed_empty:
        missing.append("响应体")

    hints = []
    if not (norm.get("req_headers") or "").strip():
        hints.append("请求头")
    if not (norm.get("resp_headers") or "").strip():
        hints.append("响应头")

    if missing:
        text = "缺" + "、".join(missing)
        if hints:
            text += f"；另无{'、'.join(hints)}"
        return PARTIAL, text
    if hints:
        # 四要素齐但缺头：算完整，但把提示带上，让人自己判断
        return FULL, f"无{'、'.join(hints)}（不影响复核返回内容）"
    return FULL, ""


def spill_figure(body):
    """判断响应体要不要落盘。返回 (to_spill, chars, bytes, sha256)。"""
    chars = len(body or "")
    raw = (body or "").encode("utf-8")
    return chars > INLINE_CHARS, chars, len(raw), hashlib.sha256(raw).hexdigest()


def spill_name(sha, chars):
    """落盘文件名。只由 sha 与长度拼成，不含任何用户输入，天然无路径穿越。"""
    return f"{sha[:16]}-{chars}.txt"


def render_text(norm, resp_body=None, req_body=None):
    """把结构化报文渲染成人读文本。

    用途：文字证据摘要的替代品、下载原文时的信封、以及给 AI 单条读取时的
    紧凑形式。响应体传 None 表示"已在别处（落盘文件）"。
    """
    body = norm.get("resp_body") if resp_body is None else resp_body
    rq = norm.get("req_body") if req_body is None else req_body
    lines = []
    if norm.get("label"):
        lines.append(f"# {norm['label']}")
    url = norm.get("req_url") or ""
    lines.append(f"{norm.get('req_method', '')} {url}")
    if norm.get("req_query"):
        lines.append(f"query: {norm['req_query']}")
    if norm.get("req_headers"):
        lines.append("--- REQUEST HEADERS ---")
        lines.append(norm["req_headers"])
    if (rq or "").strip():
        lines.append("--- REQUEST BODY ---")
        lines.append(rq)
    dur = norm.get("duration_ms")
    tail = f"，{dur}ms" if dur is not None else ""
    lines.append(f"--- RESPONSE {norm.get('resp_status')}{tail} ---")
    if norm.get("resp_headers"):
        lines.append("--- RESPONSE HEADERS ---")
        lines.append(norm["resp_headers"])
    lines.append("--- RESPONSE BODY ---")
    if body is None:
        lines.append("（响应体较大，已存为附件，见 resp_body_file）")
    else:
        lines.append(body if body else "（空）")
    return "\n".join(lines)


# ---------- 原始报文还原（raw 出口） ----------
# 页面把一条包拆成"请求列 / 响应列"是为了对照着看，但证据的本质是抓包那一刻
# 的报文：审核的人要判断的是"这条请求打出去、后端到底回了什么"，不是模板
# 重排后的表格。这里只做一件事——把结构化字段**原样拼回去**：
#   - 头按入库顺序全给，不筛不并（筛掉"噪音头"等于替读者做判断）
#   - body 一个字符不改，大响应也不截（截断过的证据不可复核）
#   - 只补一个 Host：库里存的是绝对 URL 而头里没记 Host 时才补，不臆造别的
# 唯一的自由发挥是状态行的 reason（1xx-5xx 常用词表），缺失就不写。

REASONS = {
    200: "OK", 201: "Created", 202: "Accepted", 204: "No Content",
    301: "Moved Permanently", 302: "Found", 304: "Not Modified",
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
    405: "Method Not Allowed", 406: "Not Acceptable", 408: "Request Timeout",
    409: "Conflict", 410: "Gone", 413: "Payload Too Large",
    415: "Unsupported Media Type", 422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error", 501: "Not Implemented", 502: "Bad Gateway",
    503: "Service Unavailable", 504: "Gateway Timeout",
}


def header_pairs(raw):
    """头字段（入库时是 JSON 文本）→ [(name, value)]，保持原有顺序。

    解析不了的（历史脏数据）整段当一行输出，宁可难看也不丢字段。
    """
    if not raw:
        return []
    try:
        val = json.loads(raw)
    except Exception:
        return [("", str(raw))]
    if isinstance(val, dict):
        return [(str(k), _as_text(v)) for k, v in val.items()]
    return [("", str(val))]


def query_text(raw):
    """库里的 req_query → `a=1&b=2`。

    入库形态是 JSON 对象（提交时传了 dict）或本来就是 query 串（老数据 /
    runner 直接拼进 URL 的情况）。JSON 走 urlencode，转义按标准来。
    """
    s = (raw or "").strip()
    if not s:
        return ""
    if s[:1] in "{[":
        try:
            obj = json.loads(s)
        except Exception:
            return s.lstrip("?")
        if isinstance(obj, dict):
            pairs = [(str(k), _as_text(v)) for k, v in obj.items() if v is not None]
            return urlencode(pairs)
        return ""
    return s.lstrip("?")


def raw_text(pkt):
    """一条数据包 → 标准 HTTP 报文（请求段 + 响应段）。

    请求行用 origin-form（`GET /path?query HTTP/1.1`），哪怕库里存的是绝对
    地址——那才是线上真正发出去的形态；host 交给 Host 头表达。

    两段之间只隔一个空行，不加注释、不加分隔线：整段复制出去就能直接和
    Postman / Charles / curl 抓到的原文逐行对比。
    """
    url = (pkt.get("req_url") or "").strip()
    path, url_query, url_host = url, "", ""
    if url.startswith(("http://", "https://")):
        sp = urlsplit(url)
        path, url_query, url_host = (sp.path or "/"), sp.query, sp.netloc
    query = url_query or query_text(pkt.get("req_query"))
    target = path + (("?" + query) if query else "")

    req_headers = header_pairs(pkt.get("req_headers"))
    lines = [f"{pkt.get('req_method') or 'GET'} {target} HTTP/1.1"]
    if url_host and not any(k.lower() == "host" for k, _ in req_headers):
        lines.append(f"Host: {url_host}")
    lines += [f"{k}: {v}" if k else v for k, v in req_headers]

    status = pkt.get("resp_status")
    reason = REASONS.get(status, "")
    out = "\n".join(lines) + "\n\n"

    req_body = pkt.get("req_body") or ""
    if req_body:
        out += req_body + "\n\n"

    out += f"HTTP/1.1 {status}" + (f" {reason}" if reason else "") + "\n"
    resp_headers = header_pairs(pkt.get("resp_headers"))
    if resp_headers:
        out += "\n".join(f"{k}: {v}" if k else v for k, v in resp_headers) + "\n"

    return out + "\n" + (pkt.get("resp_body") or "")


def raw_name(pkid):
    """下载文件名。只由 id 拼成，不含任何用户输入。"""
    return f"packet-{pkid}.http"
