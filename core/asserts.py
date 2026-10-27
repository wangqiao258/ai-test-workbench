"""断言引擎：把 steps_json 里的 checks 判成 pass / fail。

纯函数，不出网、不连库、不依赖 Flask——单测直接喂 dict。

check 形状（API 步骤）：
    {"src": "status",                    "op": "eq",  "value": 200}
    {"src": "body", "path": "$.code",    "op": "ne",  "value": 0}
    {"src": "body", "path": "$.data.accessToken", "op": "absent"}
    {"src": "headers", "path": "content-type", "op": "contains", "value": "json"}
    {"src": "duration_ms",               "op": "lt",  "value": 800}

check 形状（UI 步骤，取的是"页面快照"而不是 HTTP 响应）：
    {"src": "url",                     "op": "contains", "value": "/home"}
    {"src": "title",                   "op": "eq",       "value": "待办"}
    {"src": "text",                    "op": "contains", "value": "登录成功"}
    {"src": "element", "path": "登录",  "op": "absent"}

同一套 op 判两种上下文——UI 只是把取值来源从响应换成页面，
规则不另写一份（这份文件被 runner 和平台共用，分叉过一次）。

`path` 是简化 jsonpath：`$.a.b[0].c`，只支持点号与数组下标，
不支持通配、切片、过滤——够用，且不引第三方库。
"""

import json
import re

# API 步骤能取的值
SRCS_API = ("status", "body", "headers", "duration_ms")
# UI 步骤能取的值：页面快照（地址 / 标题 / 可见文本 / 指定元素的文本）
SRCS_UI = ("url", "title", "text", "element")
# 全集（调用方不区分上下文时的默认值）
SRCS = SRCS_API + SRCS_UI

OPS = ("eq", "ne", "contains", "not_contains", "present", "absent",
       "gt", "lt", "regex", "in")

# 不需要 value 的运算符
_NO_VALUE_OPS = ("present", "absent")

_PATH_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def parse_path(path):
    """`$.data.list[0].name` -> ['data','list',0,'name']；空/`$` -> []。"""
    p = (path or "").strip()
    if p.startswith("$"):
        p = p[1:]
    if p.startswith("."):
        p = p[1:]
    if not p:
        return []
    out = []
    for m in _PATH_RE.finditer(p):
        if m.group(1) is not None:
            out.append(m.group(1))
        else:
            out.append(int(m.group(2)))
    return out


def get_path(obj, tokens):
    """按 token 取值，返回 (是否存在, 值)。类型不匹配一律当不存在。"""
    cur = obj
    for t in tokens:
        if isinstance(t, int):
            if not isinstance(cur, list) or t >= len(cur) or t < -len(cur):
                return False, None
            cur = cur[t]
        else:
            if not isinstance(cur, dict) or t not in cur:
                return False, None
            cur = cur[t]
    return True, cur


def _as_json(text):
    """响应体尝试解析成 JSON；不是 JSON 返回 (None, False)。"""
    if isinstance(text, (dict, list)):
        return text, True
    if not isinstance(text, str):
        return None, False
    s = text.strip()
    if not s or s[0] not in "{[":
        return None, False
    try:
        return json.loads(s), True
    except (ValueError, TypeError):
        return None, False


def _probe(src, path, ctx):
    """按 src/path 取出 (found, value)。"""
    if src == "status":
        val = ctx.get("status")
        return (val is not None), val
    if src == "duration_ms":
        val = ctx.get("duration_ms")
        return (val is not None), val
    if src == "headers":
        headers = ctx.get("headers") or {}
        toks = parse_path(path) if path else []
        if not toks:
            return (bool(headers)), headers
        # 响应头大小写不敏感，且常带连字符（content-type）
        lowered = {str(k).lower(): v for k, v in headers.items()}
        key = str(toks[0]).lower()
        if key not in lowered:
            return False, None
        return (True, lowered[key])
    # ---- 以下四个 src 只在 UI 步骤里出现，值来自页面快照 ----
    if src in ("url", "title", "text"):
        val = ctx.get(src)
        return (val is not None), val
    if src == "element":
        # path 写的是元素定位描述（与 ui.target 同一份字符串），
        # runner 执行这一步时把解析到的元素文本塞进 ctx["elements"]。
        els = ctx.get("elements") or {}
        key = (path or "").strip()
        if not key:
            return (bool(els)), els
        if key not in els:
            return False, None
        return (True, els[key])
    # body：不带 path 时按**原始文本**判断（contains/regex 的直觉语义），
    # 带 path 才解析 JSON 取字段——反过来的话 {"a":1} contains "a" 会变成查字典键。
    body = ctx.get("body")
    toks = parse_path(path) if path else []
    if not toks:
        return (body is not None), body
    parsed, is_json = _as_json(body)
    if not is_json:
        return False, None
    return get_path(parsed, toks)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _judge(op, found, actual, expect):
    """单个 check 的判定。found=False 时除 absent 外一律不通过。"""
    if op == "absent":
        return (not found) or actual is None
    if not found:
        return False
    if op == "present":
        return actual is not None
    if op == "eq":
        return actual == expect
    if op == "ne":
        return actual != expect
    if op == "contains":
        if isinstance(actual, (list, tuple)):
            return expect in actual
        if isinstance(actual, dict):
            return expect in actual
        return str(expect) in str(actual)
    if op == "not_contains":
        if isinstance(actual, (list, tuple, dict)):
            return expect not in actual
        return str(expect) not in str(actual)
    if op in ("gt", "lt"):
        a, b = _num(actual), _num(expect)
        if a is None or b is None:
            return False
        return a > b if op == "gt" else a < b
    if op == "regex":
        try:
            return re.search(str(expect), str(actual)) is not None
        except re.error:
            return False
    if op == "in":
        if not isinstance(expect, (list, tuple)):
            return False
        return actual in expect
    return False


def _describe(chk, found, actual):
    where = chk["src"] + (f"[{chk['path']}]" if chk.get("path") else "")
    op = chk["op"]
    if op in _NO_VALUE_OPS:
        want = op
    else:
        want = f"{op} {json.dumps(chk.get('value'), ensure_ascii=False)}"
    got = json.dumps(actual, ensure_ascii=False) if found else "<不存在>"
    if isinstance(got, str) and len(got) > 120:
        got = got[:120] + "…"
    return f"{where} {want}，实际 {got}"


def evaluate(checks, ctx):
    """跑一组 checks，返回 (全部通过, 失败描述列表)。

    空 checks 视为"没有断言"——调用方（runner）应当在执行前就跳过这种用例，
    这里给 False 是为了不把"没断言"误判成通过。
    """
    if not checks:
        return False, ["没有 checks，无法判定"]
    failures = []
    for chk in checks:
        found, actual = _probe(chk["src"], chk.get("path"), ctx)
        if not _judge(chk["op"], found, actual, chk.get("value")):
            failures.append(_describe(chk, found, actual))
    return (not failures), failures


def normalize_checks(raw, step_no=1, allowed=SRCS):
    """校验并规范化一条步骤的 checks，返回 (list, err)。

    allowed 按步骤类型收窄可选 src：API 步骤不收页面断言（url/title/text/element），
    UI 步骤不收响应断言——写错了当场报，别等跑到一半才说"取不到值"。
    """
    allowed = allowed or SRCS
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, f"第 {step_no} 步 checks 应为数组"
    if not raw:
        return [], None
    if len(raw) > 30:
        return None, f"第 {step_no} 步 checks 最多 30 条"
    out = []
    for i, c in enumerate(raw, 1):
        if not isinstance(c, dict):
            return None, f"第 {step_no} 步第 {i} 条 check 不是对象"
        src = (c.get("src") or "").strip()
        if src not in allowed:
            return None, (f"第 {step_no} 步第 {i} 条 check 的 src 非法: {src}"
                          f"（可选 {'/'.join(allowed)}）")
        op = (c.get("op") or "").strip()
        if op not in OPS:
            return None, f"第 {step_no} 步第 {i} 条 check 的 op 非法: {op}（可选 {'/'.join(OPS)}）"
        item = {"src": src, "op": op}
        path = (c.get("path") or "").strip()
        if path:
            item["path"] = path
        if op not in _NO_VALUE_OPS:
            if "value" not in c:
                return None, f"第 {step_no} 步第 {i} 条 check（{op}）缺 value"
            item["value"] = c["value"]
        if op == "regex":
            try:
                re.compile(str(item["value"]))
            except re.error as exc:
                return None, f"第 {step_no} 步第 {i} 条 check 的正则非法: {exc}"
        out.append(item)
    return out, None
