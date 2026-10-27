"""结构化步骤：校验、渲染成人看的文本、分步结果推导。无 IO。"""

import json

from core.asserts import SRCS, SRCS_API, SRCS_UI, normalize_checks

STEP_KINDS = ("api", "ui", "mixed")

HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")

# UI 动作只留四个：能覆盖"打开页 → 填 → 点 → 等"这条最短闭环。
# 没有 hover / 拖拽 / 上传——真需要时再加，先不为想象中的场景写代码。
UI_DOS = ("goto", "click", "fill", "wait", "eval")

UI_DO_LABEL = {"goto": "打开", "click": "点击", "fill": "输入", "wait": "等待", "eval": "执行脚本"}

def _norm_target(raw, idx):
    """元素定位。字符串=按文本找；对象三选一 text / role(+name) / css。

    留三种是因为被测前端是 uni-app：编译后是 <uni-view>/<uni-button> 这类
    自定义标签，没有隐式 ARIA role，get_by_role 未必抓得到。哪个稳用哪个，
    不预设——先让录制时的事实决定。
    """
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None, f"第 {idx} 步 ui.target 不能为空"
        return {"text": text}, None
    if not isinstance(raw, dict):
        return None, f"第 {idx} 步 ui.target 应为字符串或对象（text/css/role 三选一）"
    keys = [k for k in ("text", "css", "role") if str(raw.get(k) or "").strip()]
    if len(keys) != 1:
        return None, f"第 {idx} 步 ui.target 需要且只能给 text / css / role 之一"
    key = keys[0]
    out = {key: str(raw[key]).strip()}
    if key == "role":
        name = str(raw.get("name") or "").strip()
        if name:
            out["name"] = name
    return out, None


def normalize_ui(raw, idx):
    """校验并规范化单步的 ui 动作，返回 (dict, err)。

    域名不进 ui.url——跟 request.path 同一条规矩，域名归环境 base_url 管，
    换内网 IP 时只改一处。
    """
    if not isinstance(raw, dict):
        return None, f"第 {idx} 步 ui 应为对象"
    do = str(raw.get("do") or "").strip().lower()
    if do not in UI_DOS:
        return None, f"第 {idx} 步 ui.do 非法: {do or '(空)'}（可选 {'/'.join(UI_DOS)}）"
    out = {"do": do}

    if do == "eval":
        script = str(raw.get("script") or "").strip()
        if not script:
            return None, f"第 {idx} 步 ui.script 不能为空（要执行的 JS）"
        out["script"] = script
        return out, None

    if do == "goto":
        url = str(raw.get("url") or "").strip()
        if not url.startswith("/") or "://" in url:
            return None, (f"第 {idx} 步 ui.url 只能写路径（如 /pages/index/index），"
                          "不能带域名——域名由环境 base_url 决定")
        out["url"] = url
        return out, None

    if do == "wait":
        target = raw.get("target")
        ms = raw.get("ms")
        if target:
            t, err = _norm_target(target, idx)
            if err:
                return None, err
            out["target"] = t
        elif isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms > 0:
            out["ms"] = int(ms)
        else:
            return None, f"第 {idx} 步 ui.do=wait 需要 target（等某元素出现）或 ms（等固定毫秒）"
        return out, None

    # click / fill 都要 target
    t, err = _norm_target(raw.get("target"), idx)
    if err:
        return None, err
    out["target"] = t
    if do == "fill":
        if "value" not in raw:
            return None, f"第 {idx} 步 ui.do=fill 缺 value（要填什么）"
        out["value"] = str(raw.get("value"))
    return out, None


def normalize_steps(raw):
    """校验并规范化结构化步骤，返回 (struct, err)。

    结构：{"kind":"api|ui|mixed",
           "steps":[{"no":1,"action":"做了什么","request":{...}|"ui":{...},"expect":"怎么算通过"}]}
    规则：action 必填；expect 必填（没有断言就无法判定通过）；
         request.method 限 HTTP 动词，path 只写路径（与接口表同一套域名规矩）。
    """
    if not raw:
        return None, None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None, "steps_json 不是合法 JSON"
    if not isinstance(raw, dict):
        return None, 'steps_json 应为对象：{"kind":"api","steps":[...]}'
    kind = (raw.get("kind") or "mixed").strip().lower()
    if kind not in STEP_KINDS:
        return None, f"kind 只能是 {'/'.join(STEP_KINDS)}"
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        return None, "steps 必须是非空数组"
    if len(steps) > 50:
        return None, "steps 最多 50 步"
    out = []
    for idx, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            return None, f"第 {idx} 步不是对象"
        action = (s.get("action") or "").strip()
        if not action:
            return None, f"第 {idx} 步缺 action（这一步做了什么）"
        expect = (s.get("expect") or "").strip()
        if not expect:
            return None, f"第 {idx} 步缺 expect（怎么算通过）"
        item = {"no": s.get("no") or idx, "action": action, "expect": expect}
        req = s.get("request")
        if req:
            if not isinstance(req, dict):
                return None, f"第 {idx} 步 request 应为对象"
            method = (req.get("method") or "GET").upper()
            if method not in HTTP_METHODS:
                return None, f"第 {idx} 步 request.method 非法: {method}"
            path = (req.get("path") or "").strip()
            if not path.startswith("/") or "://" in path:
                return None, (f"第 {idx} 步 request.path 只能写路径"
                              "（如 /admin-api/system/auth/login），不能带域名")
            item["request"] = {"method": method, "path": path}
            for k in ("headers", "query", "body"):
                if isinstance(req.get(k), (dict, list)) and req[k]:
                    item["request"][k] = req[k]
        ui = s.get("ui")
        if ui:
            ui_norm, uerr = normalize_ui(ui, idx)
            if uerr:
                return None, uerr
            item["ui"] = ui_norm
        # 一步只做一件事：要么发请求，要么操作页面。混在一步里，runner 就得猜
        # "先点还是先发"，跑完也没法把这步讲清楚。
        if item.get("request") and item.get("ui"):
            return None, f"第 {idx} 步不能同时有 request 和 ui（一步只做一件事）"
        # UI 用例每步都要有页面动作——没动作的步骤跑起来是空转。
        # API 用例不逐条强制：允许夹"观察结果"这类纯说明步骤（存量就有这种写法），
        # 执行时 case_runnability 会把整条挡在 skipped，保存阶段不替人做决定。
        if kind == "ui" and not item.get("ui"):
            return None, f"第 {idx} 步缺 ui（kind=ui 的用例每步都要有页面动作）"
        # 机读断言（P1）：有 checks 的步骤才能交给 runner 自动判定；
        # 没有 checks 的用例 runner 跳过，不拿 expect 自然语言猜。
        # 可用 src 跟着步骤类型走：API 步骤不许写页面断言，反之亦然。
        checks = s.get("checks")
        if checks is not None:
            if item.get("ui"):
                allowed = SRCS_UI
            elif item.get("request"):
                allowed = SRCS_API
            else:
                allowed = SRCS
            norm, cerr = normalize_checks(checks, idx, allowed)
            if cerr:
                return None, cerr
            if norm:
                item["checks"] = norm
        out.append(item)
    if kind == "api" and not any(s.get("request") for s in out):
        return None, "kind=api 的用例至少要有一个 request 步骤"
    return {"kind": kind, "steps": out}, None

def _dumps(v):
    return json.dumps(v, ensure_ascii=False)


def _target_text(t):
    """把定位描述渲染成人话，写进 cases.steps 给审核的人看。"""
    if not isinstance(t, dict):
        return str(t)
    if t.get("text"):
        return f"[按文本]{t['text']}"
    if t.get("css"):
        return f"[CSS]{t['css']}"
    if t.get("role"):
        return f"[role={t['role']}]{t.get('name') or ''}"
    return str(t)


def render_ui_text(ui):
    """把 ui 动作渲染成一句人话：网页详情和 cases.steps 文本共用这一份。"""
    do = ui.get("do")
    if do == "goto":
        return f"打开 {ui.get('url')}"
    if do == "click":
        return f"点击 {_target_text(ui.get('target'))}"
    if do == "fill":
        return f"在 {_target_text(ui.get('target'))} 输入 {ui.get('value')}"
    if do == "wait":
        if ui.get("target"):
            return f"等待 {_target_text(ui['target'])} 出现"
        return f"等待 {ui.get('ms')}ms"
    return str(ui)


def render_steps(struct):
    """把结构化步骤渲染成人看的文本（写回 cases.steps，只维护一份数据）。"""
    lines = []
    for s in struct["steps"]:
        lines.append(f"{s['no']}. {s['action']}")
        req = s.get("request")
        if req:
            line = f"   -> {req['method']} {req['path']}"
            if req.get("query"):
                line += "  query=" + _dumps(req["query"])
            if req.get("body"):
                line += "  body=" + _dumps(req["body"])
            if req.get("headers"):
                line += "  headers=" + _dumps(req["headers"])
            lines.append(line)
        if s.get("ui"):
            lines.append("   -> " + render_ui_text(s["ui"]))
        if s.get("checks"):
            lines.append(f"   断言: {len(s['checks'])} 条（runner 按此判定）")
        lines.append(f"   预期: {s['expect']}")
    return "\n".join(lines)

def parse_steps(raw):
    """读取时的宽松解析：坏数据返回 None，不影响其他字段。"""
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else None
    except (ValueError, TypeError):
        return None

def parse_step_list(raw):
    """executions.step_results 的宽松解析。"""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (ValueError, TypeError):
        return []

def normalize_step_results(raw, case_steps):
    """校验按步回填。case_steps 为该用例的 steps_json（无结构时不做步号校验）。"""
    if not raw:
        return [], None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None, "step_results 不是合法 JSON"
    if not isinstance(raw, list):
        return None, "step_results 应为数组"
    valid = {s.get("no") for s in (case_steps or {}).get("steps", [])}
    out = []
    for idx, r in enumerate(raw, 1):
        if not isinstance(r, dict):
            return None, f"第 {idx} 条 step_result 不是对象"
        no = r.get("no")
        if valid and no not in valid:
            return None, (f"step_results 里的 no={no} 不在这条用例的步骤号里"
                          f"（可用：{sorted(valid)}）")
        result = (r.get("result") or "").strip()
        if result not in ("pass", "fail", "blocked"):
            return None, f"第 {idx} 条 step_results.result 必须是 pass/fail/blocked"
        item = {"no": no, "result": result, "actual": r.get("actual", "")}
        if r.get("evidence"):
            item["evidence"] = r["evidence"]
        out.append(item)
    return out, None

def derive_result(step_results):
    """由分步结果推导总结果：任一 fail -> fail；有 blocked 无 fail -> blocked；否则 pass。"""
    if not step_results:
        return None
    rs = [r["result"] for r in step_results]
    if "fail" in rs:
        return "fail"
    if "blocked" in rs:
        return "blocked"
    return "pass"

