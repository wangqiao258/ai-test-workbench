"""run 收尾后的 webhook 通知（独立评审修复项 12）。

边界（与决策 #6 "不要调度器"一致）：
- 只在**终态**发送——finish(done/failed) 和 cancel(→failed)。
- stalled 是只读派生状态、平台不自动收尾，所以也没有"卡住自动报警"的
  定时轮询；要发现僵死轮，看运行列表的 stalled 标记（2026-10-23 已上线）。
  真要定时巡检，那是调度器，边界上明确不加。

工程约束：
- 只用标准库 urllib，不引第三方依赖（requirements 不动）；
- 发送放守护线程 + 5 秒超时：webhook 不通不该拖住 runner 的收尾请求；
- 任何失败只记日志，绝不向上抛——通知是锦上添花，不是业务。
- 本模块不 import Flask/db：配置由调用方（api 层）读好传进来，
  payload 形状与发送是纯逻辑，可单测。
"""

import json
import logging
import threading
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

# notify.on 的合法值，与 runs.status 对齐（cancel 落的是 failed）
NOTIFY_EVENTS = ("done", "failed")
# wecom = 企业微信机器人（msgtype/text）；generic = 通用 JSON（event/run/text）
NOTIFY_FORMATS = ("wecom", "generic")
NOTIFY_TIMEOUT = 5


def validate_notify(value):
    """notify = {"webhook_url": "https://...", "on": ["failed"], "format": "wecom"}

    返回 (规范化值, err)。URL 只允许 http/https——file:// 之类会让 urllib
    去做读本地文件之类的怪事；on 缺省两种终态都发。
    """
    if not isinstance(value, dict):
        return None, "notify 应为对象，如 {\"webhook_url\": \"https://...\"}"
    url = str(value.get("webhook_url") or "").strip()
    if not url:
        return None, "webhook_url 必填（企业微信机器人/钉钉/飞书的 webhook 地址）"
    if not url.startswith(("http://", "https://")):
        return None, "webhook_url 只支持 http/https"
    raw_on = value.get("on") or list(NOTIFY_EVENTS)
    if not isinstance(raw_on, list) or not raw_on:
        return None, f"on 应为数组，可选 {'/'.join(NOTIFY_EVENTS)}"
    on = []
    for ev in raw_on:
        ev = str(ev).strip().lower()
        if ev not in NOTIFY_EVENTS:
            return None, f"on 里的 {ev!r} 不合法，只能是 {'/'.join(NOTIFY_EVENTS)}"
        if ev not in on:
            on.append(ev)
    fmt = str(value.get("format") or "wecom").strip().lower()
    if fmt not in NOTIFY_FORMATS:
        return None, f"format 只能是 {'/'.join(NOTIFY_FORMATS)}"
    return {"webhook_url": url, "on": on, "format": fmt}, None


def should_notify(setting, status):
    """没配 webhook、或这个终态不在 on 里，就不发。"""
    if not setting or not setting.get("webhook_url"):
        return False
    return status in (setting.get("on") or ())


def _text_line(run):
    """人读的一行摘要：企业微信/钉钉的消息正文，也放进 generic 的 text 字段。"""
    s = run.get("summary") or {}
    verdict = {"done": "跑完", "failed": "失败/收尾"}.get(run.get("status"), run.get("status"))
    line = (f"测试轮 #{run.get('id')}「{run.get('name') or '(未命名)'}」{verdict}："
            f"共 {s.get('total', 0)} 条，"
            f"过 {s.get('pass', 0)} / 败 {s.get('fail', 0)} / "
            f"阻 {s.get('blocked', 0)} / 跳 {s.get('skipped', 0)}")
    if run.get("kind") and run["kind"] != "regression":
        line += f"（{run['kind']}）"
    note = s.get("note") or run.get("cancel_note")
    if note:
        line += f"；备注：{note}"
    return line


def build_payload(run, fmt):
    """按 format 拼 webhook 请求体。run 需含 id/name/kind/status/summary。"""
    if fmt == "wecom":
        # 企业微信机器人：msgtype=text，content 最长 2048 字节
        return {"msgtype": "text", "text": {"content": _text_line(run)[:2000]}}
    return {
        "event": "run.finished",
        "run": {
            "id": run.get("id"), "project_id": run.get("project_id"),
            "name": run.get("name"), "kind": run.get("kind"),
            "status": run.get("status"), "summary": run.get("summary") or {},
            "finished_at": run.get("finished_at"),
            "baseline_run_id": run.get("baseline_run_id"),
        },
        "text": _text_line(run),
    }


def post_webhook(url, payload, timeout=NOTIFY_TIMEOUT):
    """同步 POST。返回 (ok, detail)。任何网络/HTTP 错误都变成 (False, 原因)。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read()[:200]!r}"
    except Exception as exc:               # 超时/DNS/连接拒绝都算发不出去
        return False, f"{type(exc).__name__}: {exc}"


def notify_run_finished(setting, run):
    """入口：该发就异步发。setting 是校验过的 notify 配置（或 None）。"""
    if not should_notify(setting, run.get("status")):
        return False
    payload = build_payload(run, setting.get("format") or "wecom")

    def _send():
        ok, detail = post_webhook(setting["webhook_url"], payload)
        if ok:
            log.info("webhook 通知已发送 run %s -> %s", run.get("id"), detail)
        else:
            log.warning("webhook 通知失败 run %s：%s", run.get("id"), detail)

    threading.Thread(target=_send, daemon=True,
                     name=f"notify-run-{run.get('id')}").start()
    return True
