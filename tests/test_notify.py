"""运行通知纯逻辑单测（修复项 12）：校验、payload 形状、真实 HTTP 发送。

不连库、不起 Flask。post_webhook 用本地 http.server 起一次性服务验证，
不碰外网（CI/离线也能跑）。

用法：python tests/test_notify.py
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.notify import (build_payload, notify_run_finished,  # noqa: E402
                         post_webhook, should_notify, validate_notify)

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond:
        fails.append(name)


print("== validate_notify ==")
cfg, err = validate_notify({"webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x"})
check("合法配置", err is None and cfg["format"] == "wecom" and cfg["on"] == ["done", "failed"],
      str(cfg))
cfg2, err2 = validate_notify({"webhook_url": "http://hook.test/x", "on": ["failed"],
                              "format": "generic"})
check("自定义 on/format", err2 is None and cfg2["on"] == ["failed"] and cfg2["format"] == "generic")
check("on 去重", validate_notify({"webhook_url": "https://a.test/", "on": ["done", "done"]})[0]["on"] == ["done"])
check("缺 url", validate_notify({"format": "wecom"})[1] is not None)
check("空 url", validate_notify({"webhook_url": "  "})[1] is not None)
check("非 http 协议", validate_notify({"webhook_url": "file:///etc/passwd"})[1] is not None)
check("on 非法值", validate_notify({"webhook_url": "https://a.test/", "on": ["stalled"]})[1] is not None)
check("on 不是数组", validate_notify({"webhook_url": "https://a.test/", "on": "done"})[1] is not None)
check("format 非法", validate_notify({"webhook_url": "https://a.test/", "format": "slack"})[1] is not None)
check("整体不是对象", validate_notify("https://a.test/")[1] is not None)

print("\n== should_notify ==")
check("没配置不发", not should_notify(None, "done"))
check("配置缺 url 不发", not should_notify({"on": ["done"]}, "done"))
check("on 里没有该终态不发", not should_notify(
    {"webhook_url": "https://a.test/", "on": ["failed"]}, "done"))
check("终态在 on 里才发", should_notify(
    {"webhook_url": "https://a.test/", "on": ["done", "failed"]}, "failed"))

print("\n== build_payload ==")
run = {"id": 12, "project_id": 1, "name": "登录模块回归", "kind": "regression",
       "status": "done", "summary": {"total": 21, "pass": 18, "fail": 2, "blocked": 1,
                                     "skipped": 0}, "finished_at": "2026-10-26 12:00:00"}
wecom = build_payload(run, "wecom")
check("wecom 形状", wecom.get("msgtype") == "text" and "content" in wecom["text"])
check("wecom 正文含关键数字", "共 21 条" in wecom["text"]["content"] and "过 18" in wecom["text"]["content"])
check("wecom 正文含轮次名", "登录模块回归" in wecom["text"]["content"])
generic = build_payload(run, "generic")
check("generic 形状", generic["event"] == "run.finished" and generic["run"]["id"] == 12)
check("generic 带 text", "共 21 条" in generic["text"])
run_f = dict(run, status="failed", kind="selfcheck", cancel_note="runner 被关窗")
line = build_payload(run_f, "wecom")["text"]["content"]
check("失败/自检轮也有正文", "失败/收尾" in line and "selfcheck" in line and "runner 被关窗" in line)

print("\n== post_webhook（本地一次性服务） ==")
received = {}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        received["path"] = self.path
        received["body"] = json.loads(body.decode("utf-8"))
        received["ctype"] = self.headers.get("Content-Type")
        if self.path == "/fail":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"errcode":0}')

    def log_message(self, *a):        # 静音
        pass


srv = HTTPServer(("127.0.0.1", 0), _Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"

ok, detail = post_webhook(base + "/ok", {"hello": "世界"})
check("200 判定成功", ok, detail)
check("请求体原样到达", received.get("body") == {"hello": "世界"})
check("Content-Type 是 json", received.get("ctype", "").startswith("application/json"))
ok2, detail2 = post_webhook(base + "/fail", {"a": 1})
check("500 判定失败", not ok2 and "500" in detail2, detail2)
ok3, detail3 = post_webhook("http://127.0.0.1:1/nope", {"a": 1}, timeout=2)
check("连不判定失败", not ok3, detail3)
srv.shutdown()

print("\n== notify_run_finished（异步不抛） ==")
sent = []
orig = post_webhook


def _fake(url, payload, timeout=5):
    sent.append((url, payload))
    return True, "HTTP 200"


import core.notify as notify_mod                      # noqa: E402
notify_mod.post_webhook = _fake
try:
    threading_orig = notify_mod.threading
    # 同步执行线程体，避免测试里等定时
    class _SyncThread:
        def __init__(self, target=None, daemon=False, name=None):
            self._t = target
        def start(self):
            self._t()
    notify_mod.threading = type("T", (), {"Thread": _SyncThread})
    fired = notify_mod_fired = notify_mod.notify_run_finished(
        {"webhook_url": "https://hook.test/x", "on": ["done"], "format": "wecom"},
        {"id": 1, "name": "t", "status": "done", "summary": {"total": 1, "pass": 1}})
    check("命中 on 时触发发送", fired and len(sent) == 1)
    check("payload 用的是传入配置", sent and sent[0][0] == "https://hook.test/x"
          and sent[0][1]["msgtype"] == "text")
    sent.clear()
    again = notify_mod.notify_run_finished(
        {"webhook_url": "https://hook.test/x", "on": ["failed"], "format": "wecom"},
        {"id": 1, "name": "t", "status": "done", "summary": {}})
    check("不在 on 里不发送", not again and not sent)
    check("配置为 None 不发送", not notify_mod.notify_run_finished(None, {"status": "done"}))
finally:
    notify_mod.post_webhook = orig
    notify_mod.threading = threading_orig

print()
if fails:
    print(f"失败 {len(fails)} 项：" + "；".join(fails))
    sys.exit(1)
print("全部通过")
