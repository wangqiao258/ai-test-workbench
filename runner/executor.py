"""单条用例的执行：逐步执行 → 断言判定 → 回填 execution → 挂数据包。

两条边界：
- API 步骤的完整报文都提交 `POST /api/packets`（平台做完整性判定，永不截断）
- 一步异常只把该步记 blocked，继续后面的步骤；整条的结果由平台按步推导

P2 起同一个循环里跑两种步骤：`request` 走 requests，`ui` 走 Playwright。
断言都落到 `core/asserts.evaluate`——UI 只是把取值来源换成页面快照，
判定规则不另写一份。UI 步骤不产生数据包（packet 是 HTTP 报文，
页面操作没有报文，硬塞进去会让 /packets 里出现语义错误的状态码）。
"""

import json
import os
import re
import time
import warnings

import requests
import urllib3

from core.asserts import evaluate

from .client import ApiError

# 内网测试环境多为自签证书，VERIFY_SSL=0 时不必每步都刷一条 InsecureRequestWarning
warnings.filterwarnings("ignore", message="Unverified HTTPS request")
urllib3.disable_warnings()

# 步骤间取值：{{steps.1.data.accessToken}} / {{account.username}}
# 这是"登录拿 token 再去调业务接口"这类用例能跑起来的前提。
_TPL = re.compile(r"\{\{([^{}]+)\}\}")


def _lookup(expr, ctx):
    cur = ctx
    for part in expr.strip().split("."):
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
            elif part.isdigit() and int(part) in cur:   # steps 的键是整数 1，模板里是 "1"
                cur = cur[int(part)]
            else:
                return None, False
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None, False
    return cur, True


def _render(value, ctx):
    """递归替换模板。整串是一个占位符时保留原类型（数字仍是数字）。"""
    if isinstance(value, dict):
        return {k: _render(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, ctx) for v in value]
    if not isinstance(value, str):
        return value
    whole = _TPL.fullmatch(value.strip())
    if whole:
        val, ok = _lookup(whole.group(1), ctx)
        return val if ok else value       # 取不到就原样留着，让请求自己暴露问题
    return _TPL.sub(lambda m: str(_lookup(m.group(1), ctx)[0] or ""), value)


def _text(value):
    if value in (None, ""):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _body_kw(body):
    if isinstance(body, (dict, list)):
        return {"json": body}
    if isinstance(body, str) and body:
        return {"data": body.encode("utf-8")}
    return {}


def _parse_json(text):
    """响应体尝试解析 JSON，给后续步骤的 {{steps.N...}} 取值用。"""
    s = (text or "").strip()
    if not s or s[0] not in "{[":
        return None, False
    try:
        return json.loads(s), True
    except (ValueError, TypeError):
        return None, False


def _derive(step_results):
    rs = [r["result"] for r in step_results]
    if "fail" in rs:
        return "fail"
    if "blocked" in rs:
        return "blocked"
    return "pass"


def _case_packet(project_id, case, step, resp, duration, sent_body):
    return {
        "project_id": project_id,
        "linked_type": "execution",
        "label": f"{case['title']} / 第{step.get('no')}步 {step.get('action', '')}"[:150],
        "request": {
            "method": (step.get("request") or {}).get("method"),
            "url": resp.request.url,
            "headers": dict(resp.request.headers),
            "body": _text(sent_body),
        },
        "response": {
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "body": resp.text,
            "duration_ms": duration,
        },
    }


def _run_ui_step(browser, step, ctx, shot_dir, run_id, case):
    """一步页面操作。返回 (result, actual, evidence)。

    与 API 步骤的区别只有"动作"和"快照从哪来"：判定仍是 evaluate(checks, 快照)。
    页面执行异常记 blocked——元素没出现、页面跳走、浏览器崩了，都属于
    "这条没验成"，不是"功能有问题"，不能算 fail（那是假缺陷）。
    """
    no = step.get("no")
    ui = step.get("ui") or {}
    if browser is None:
        return "blocked", "这条用例要 UI 步骤，但 runner 没有可用的浏览器", ""

    def _shot():
        if not shot_dir:
            return ""
        try:
            path = browser.screenshot(
                os.path.join(shot_dir, f"run{run_id}-case{case['id']}-step{no}.png"))
            return os.path.basename(path) if path else ""
        except Exception:                     # noqa: BLE001 截图失败不影响结论
            return ""

    started = time.monotonic()
    try:
        url = browser.dispatch(ui)
        snap = browser.snapshot([ui.get("target")])
        duration = int((time.monotonic() - started) * 1000)
        ctx["steps"][no] = {
            "status": None,
            "body": snap,
            "raw": snap.get("text") or "",
            "headers": {"x-ui-title": snap.get("title") or ""},
            "url": snap.get("url") or "",
        }
        ok, failures = evaluate(step.get("checks") or [], snap)
        result = "pass" if ok else "fail"
        actual = "断言全部通过" if ok else "；".join(failures)
        evidence = (f"{ui.get('do')} → {url}（{duration}ms，"
                    f"标题「{snap.get('title') or ''}」）")
        if result == "fail":
            shot = _shot()
            if shot:
                evidence += f"，失败截图 {shot}"
        return result, actual, evidence
    except Exception as exc:                  # noqa: BLE001 浏览器异常一律 blocked
        ctx["steps"][no] = {"status": None, "body": None, "raw": "", "headers": {}}
        shot = _shot()
        evidence = f"截图 {shot}" if shot else ""
        return "blocked", f"页面执行异常：{exc}", evidence


def execute_case(platform, run_id, project_id, case, base_url, base_headers,
                 timeout=30, account=None, verify=True, variables=None,
                 browser=None, shot_dir=None):
    """执行一条用例，返回 {case_id, result, execution_id, steps}。

    步骤之间可以取值：`{{steps.<步骤号>.<字段路径>}}`、`{{account.username}}`、
    `{{vars.<键>}}`（项目级变量，token 这类易过期值只存一处）。
    第 N 步执行完后，它的 status/body/raw/headers 会进上下文，供后面的步骤引用。
    """
    struct = case.get("steps_json") or {}
    steps = struct.get("steps") or []
    step_results, captured = [], []
    ctx = {"steps": {}, "account": account or {}, "vars": variables or {}}
    # 用内网 IP 直连时后端按 Host 路由，必须把域名补回 Host 头（用例显式写的会覆盖它）
    host_header = (variables or {}).get("hostHeader")

    for step in steps:
        # 每步打一次心跳：一条用例里有多个 30s 超时的步骤时，只按"条"打点会让
        # 平台误判僵死（实测一条用例最长 151 秒）。心跳失败不影响执行本身。
        try:
            platform.heartbeat(run_id)
        except ApiError:
            pass
        no = step.get("no")
        # UI 步骤：动作交给浏览器，判定仍走同一个 evaluate(checks, 快照)
        if step.get("ui"):
            result, actual, ui_evidence = _run_ui_step(
                browser, step, ctx, shot_dir, run_id, case)
            item = {"no": no, "result": result, "actual": actual}
            if ui_evidence:
                item["evidence"] = ui_evidence
            step_results.append(item)
            continue
        req = _render(step.get("request") or {}, ctx)
        url = base_url.rstrip("/") + (req.get("path") or "")
        headers = {}
        if host_header:
            headers["Host"] = str(host_header)
        headers.update(base_headers)
        for k, v in (req.get("headers") or {}).items():
            headers[str(k)] = str(v)
        kwargs = {"headers": headers, "timeout": timeout, "allow_redirects": False,
                  "verify": verify}
        if req.get("query"):
            kwargs["params"] = req["query"]
        kwargs.update(_body_kw(req.get("body")))

        started = time.monotonic()
        try:
            resp = requests.request(req.get("method") or "GET", url, **kwargs)
            duration = int((time.monotonic() - started) * 1000)
            parsed, is_json = _parse_json(resp.text)
            ctx["steps"][no] = {
                "status": resp.status_code,
                "body": parsed if is_json else resp.text,
                "raw": resp.text,
                "headers": dict(resp.headers),
            }
            ok, failures = evaluate(step.get("checks") or [], {
                "status": resp.status_code,
                "headers": dict(resp.headers),
                "body": resp.text,
                "duration_ms": duration,
            })
            result = "pass" if ok else "fail"
            actual = "断言全部通过" if ok else "；".join(failures)
            captured.append(_case_packet(project_id, case, step, resp, duration,
                                         kwargs.get("json", kwargs.get("data"))))
        except requests.RequestException as exc:
            result = "blocked"
            actual = f"请求异常：{exc}"
            ctx["steps"][no] = {"status": None, "body": None, "raw": "", "headers": {}}
        except Exception as exc:                      # noqa: BLE001 断言引擎的意外输入
            result = "blocked"
            actual = f"执行异常：{exc}"
            ctx["steps"][no] = {"status": None, "body": None, "raw": "", "headers": {}}
        step_results.append({"no": no, "result": result, "actual": actual})

    total = len(step_results)
    passed = sum(1 for r in step_results if r["result"] == "pass")
    result = _derive(step_results) if step_results else "blocked"
    actual_result = "" if result == "pass" else "；".join(
        f"第 {r['no']} 步 {r['result']}：{r['actual']}" for r in step_results
        if r["result"] != "pass")
    evidence = f"runner 自动执行（run {run_id}），{total} 步，{passed} 步断言通过。"
    # UI 用例没有 HTTP 报文，写"报文见数据包"会让人去 /packets 里白找一遍
    if (struct.get("kind") or "").lower() == "ui":
        evidence += "页面快照与截图见分步记录。"
    else:
        evidence += "报文见关联数据包。"

    execution = platform.add_execution(case["id"], {
        "run_id": run_id,
        "step_results": step_results,
        "actual_result": actual_result,
        "evidence": evidence,
    })

    for packet in captured:
        packet["linked_id"] = execution["id"]
        try:
            platform.add_packet(packet)
        except ApiError as exc:
            # 报文挂不上不影响执行结论，但要在日志里留痕
            print(f"  ! 数据包写入失败 case={case['id']} execution={execution['id']}: {exc}")

    return {
        "case_id": case["id"],
        "execution_id": execution["id"],
        "result": result,
        "steps": total,
    }
