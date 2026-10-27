"""core/ 纯规则单测：不连数据库、不起 Flask，直接跑。

用法：python tests/test_core.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.runs import (cancelled_summary, case_runnability, is_stalled,  # noqa: E402
                       normalize_kind, progress_of, run_progress, stall_cutoff)
from core.steps import (derive_result, normalize_step_results,  # noqa: E402
                        normalize_steps, render_steps)
from core.validation import (normalize_dims, normalize_host,  # noqa: E402
                             normalize_path, validate_doc)

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond:
        fails.append(name)


print("== 文档类型 ==")
check("interface 类型已废弃", validate_doc("interface", "x", "y") is not None)
check("test_plan 正文太短被拒", validate_doc("test_plan", "计划", "太短") is not None)
check("test_plan 正文够长通过", validate_doc("test_plan", "计划", "字" * 220) is None)
check("Bug 附属材料标题被拒", validate_doc("general", "登录问题复现", "正文") is not None)
check("普通文档通过", validate_doc("flow", "登录流程", "正文") is None)

print("\n== 路径 / 域名 ==")
check("缺前导斜杠自动补", normalize_path("a/b") == "/a/b")
check("带域名被拒", normalize_path("https://x.com/a") is None)
check("空路径被拒", normalize_path("  ") is None)
check("域名规范化去尾斜杠", normalize_host("https://api.x.com/") == "https://api.x.com")
check("空 host 允许", normalize_host("") == "")
check("host 带路径被拒", normalize_host("https://x.com/a") is None)

print("\n== 覆盖维度 ==")
dims, err = normalize_dims(["正常", "边界", "正常"])
check("合法维度去重", err is None and dims == ["正常", "边界"], str(dims))
check("逗号分隔字符串可解析", normalize_dims("正常,边界")[0] == ["正常", "边界"])
check("非法维度被拒", normalize_dims(["随便"])[1] is not None)

print("\n== 结构化步骤 ==")
good = {"kind": "api", "steps": [
    {"action": "调登录", "request": {"method": "POST", "path": "/admin-api/login",
                                     "body": {"u": "a"}}, "expect": "返回 token"}]}
struct, err = normalize_steps(good)
check("合法步骤通过", err is None and struct["steps"][0]["no"] == 1)
check("自动补步骤号", struct["steps"][0]["no"] == 1)
text = render_steps(struct)
check("渲染含序号与请求行", text.startswith("1. 调登录") and "-> POST /admin-api/login" in text)
check("缺 expect 被拒", normalize_steps({"steps": [{"action": "x"}]})[1] is not None)
check("非法 method 被拒", normalize_steps({"steps": [
    {"action": "x", "expect": "y", "request": {"method": "FETCH", "path": "/a"}}]})[1] is not None)
check("path 带域名被拒", normalize_steps({"steps": [
    {"action": "x", "expect": "y", "request": {"method": "GET", "path": "https://a.com/x"}}]})[1] is not None)
check("超过 50 步被拒", normalize_steps({"steps": [
    {"action": f"a{i}", "expect": "y"} for i in range(51)]})[1] is not None)
check("空 steps 被拒", normalize_steps({"steps": []})[1] is not None)

print("\n== 分步回填 ==")
srs, err = normalize_step_results([{"no": 1, "result": "fail", "actual": "401"}], struct)
check("合法分步结果", err is None and srs[0]["result"] == "fail")
check("结果值非法被拒", normalize_step_results([{"no": 1, "result": "ok"}], struct)[1] is not None)
check("步骤号越界被拒", normalize_step_results([{"no": 9, "result": "pass"}], struct)[1] is not None)
check("无结构时不校验步骤号", normalize_step_results([{"no": 9, "result": "pass"}], None)[1] is None)

check("任一 fail 推导 fail", derive_result([{"result": "pass"}, {"result": "fail"}]) == "fail")
check("有 blocked 无 fail 推导 blocked", derive_result([{"result": "pass"}, {"result": "blocked"}]) == "blocked")
check("全 pass 推导 pass", derive_result([{"result": "pass"}]) == "pass")
check("无分步返回 None", derive_result([]) is None)

print("\n== 执行观测：进度与僵死（纯函数） ==")
p = progress_of(10, ["pass"] * 3 + ["fail"] * 2 + ["blocked"] + ["不知道"])
check("进度统计三种结果", p["pass"] == 3 and p["fail"] == 2 and p["blocked"] == 1, str(p))
check("done 只数合法结果", p["done"] == 6, str(p))
check("left = total - done", p["left"] == 4, str(p))
check("空结果进度为 0", progress_of(None, [])["done"] == 0)
check("left 不为负", progress_of(1, ["pass", "pass"])["left"] == 0)

RUNNING = {"status": "running", "started_at": "2026-10-23 10:00:00"}
check("刚起心跳未超时不僵死",
      is_stalled(dict(RUNNING, last_heartbeat_at="2026-10-23 10:02:00"),
                 "2026-10-23 10:04:00") is False)
check("超 180 秒判僵死",
      is_stalled(dict(RUNNING, last_heartbeat_at="2026-10-23 10:00:59"),
                 "2026-10-23 10:04:00") is True)
check("正好 180 秒不判僵死",
      is_stalled(dict(RUNNING, last_heartbeat_at="2026-10-23 10:01:00"),
                 "2026-10-23 10:04:00") is False)
check("没有心跳退回 started_at",
      is_stalled(RUNNING, "2026-10-23 12:00:00") is True)
check("done 永不僵死",
      is_stalled({"status": "done", "started_at": "2026-10-23 10:00:00"},
                 "2026-10-23 23:00:00") is False)
check("时间格式坏掉不崩",
      is_stalled(dict(RUNNING, last_heartbeat_at="坏时间"), "2026-10-23 12:00:00") is False)
check("stall_cutoff 与阈值同口径",
      stall_cutoff("2026-10-23 10:04:00") == "2026-10-23 10:01:00")
s = cancelled_summary(5, ["pass", "fail"], "  人工取消  ")
check("取消 summary 带 note", s["note"] == "人工取消", str(s))
check("取消 summary 按实际回填算", s["pass"] == 1 and s["fail"] == 1 and s["skipped"] == 3, str(s))
check("取消 note 截断 500", len(cancelled_summary(1, [], "字" * 900)["note"]) == 500)

rp = run_progress({"status": "running", "summary": {"total": 4}},
                  ["pass", "fail"])
check("运行中按 executions 现算", rp["done"] == 2 and rp["fail"] == 1, str(rp))
rp = run_progress({"status": "done",
                   "summary": {"total": 4, "pass": 2, "fail": 1, "blocked": 0, "skipped": 1}},
                  [])
check("终态读 summary（执行记录被清也能还原）",
      rp["done"] == 3 and rp["pass"] == 2 and rp["left"] == 1, str(rp))
rp = run_progress({"status": "failed",
                   "summary": {"total": 2, "pass": 1, "fail": 1, "blocked": 0}}, [])
check("failed 也是终态", rp["done"] == 2, str(rp))

print("\n== 轮次类型 kind ==")
check("缺省 regression", normalize_kind(None) == ("regression", None), str(normalize_kind(None)))
check("空串按缺省", normalize_kind("")[0] == "regression")
check("大小写与空格归一", normalize_kind("  SELFCHECK ") == ("selfcheck", None))
check("diagnostic 合法", normalize_kind("diagnostic") == ("diagnostic", None))
check("非法值被拒", normalize_kind("smoke")[1] is not None, str(normalize_kind("smoke")))

print("\n== UI 步骤校验（P2）==")
_UI_ONE = lambda ui, checks=None, kind="ui": {"kind": kind, "steps": [
    {"action": "一步", "expect": "过了", "ui": ui, **({"checks": checks} if checks else {})}]}
_UI_CHK = [{"src": "text", "op": "contains", "value": "待办"}]

ui_ok, err = normalize_steps(_UI_ONE({"do": "goto", "url": "/pages/index/index"}, _UI_CHK))
check("goto 合法", ui_ok is not None and ui_ok["steps"][0]["ui"]["do"] == "goto", str(err))
check("渲染出人话", "打开 /pages/index/index" in render_steps(ui_ok))

bad, err = normalize_steps(_UI_ONE({"do": "goto", "url": "https://evil.test/x"}, _UI_CHK))
check("goto 拒绝带域名", bad is None and "只能写路径" in err, str(err))

bad, err = normalize_steps(_UI_ONE({"do": "click"}, _UI_CHK))
check("click 缺 target 被拒", bad is None and "target" in err, str(err))

bad, err = normalize_steps(_UI_ONE({"do": "fill", "target": "账号"}, _UI_CHK))
check("fill 缺 value 被拒", bad is None and "value" in err, str(err))

bad, err = normalize_steps(_UI_ONE({"do": "wait"}, _UI_CHK))
check("wait 缺 target 与 ms 被拒", bad is None and "wait" in err, str(err))

bad, err = normalize_steps(_UI_ONE({"do": "hover", "target": "a"}, _UI_CHK))
check("未知动作被拒", bad is None and "ui.do" in err, str(err))

bad, err = normalize_steps(_UI_ONE(
    {"do": "click", "target": {"text": "a", "css": ".b"}}, _UI_CHK))
check("target 只能三选一", bad is None and "只能给" in err, str(err))

ok_t, err = normalize_steps(_UI_ONE({"do": "click", "target": "登录"}, _UI_CHK))
check("字符串 target 归一成按文本", ok_t["steps"][0]["ui"]["target"] == {"text": "登录"})

bad, err = normalize_steps(_UI_ONE(
    {"do": "click", "target": "登录"}, [{"src": "status", "op": "eq", "value": 200}]))
check("UI 步骤不许用响应断言", bad is None and "src 非法" in err, str(err))

bad, err = normalize_steps({"kind": "api", "steps": [
    {"action": "看页面", "expect": "x", "request": {"method": "GET", "path": "/x"},
     "checks": [{"src": "text", "op": "contains", "value": "待办"}]}]})
check("API 步骤不许用页面断言", bad is None and "src 非法" in err, str(err))

bad, err = normalize_steps({"kind": "ui", "steps": [
    {"action": "只说不做", "expect": "x", "checks": _UI_CHK}]})
check("ui 用例每步必须有页面动作", bad is None and "缺 ui" in err, str(err))

bad, err = normalize_steps({"kind": "mixed", "steps": [
    {"action": "两件事", "expect": "x", "request": {"method": "GET", "path": "/x"},
     "ui": {"do": "click", "target": "a"},
     "checks": [{"src": "status", "op": "eq", "value": 200}]}]})
check("一步不能既发请求又点页面", bad is None and "一步只做一件事" in err, str(err))

print("\n== UI 用例可执行判定 ==")
ok, why = case_runnability({"kind": "ui", "steps": [
    {"no": 1, "ui": {"do": "goto", "url": "/"},
     "checks": [{"src": "url", "op": "contains", "value": "/"}]}]})
check("kind=ui 现在可以跑", ok and not why, why)
ok, why = case_runnability({"kind": "ui", "steps": [
    {"no": 1, "ui": {"do": "goto", "url": "/"}}]})
check("没 checks 的 UI 步骤仍跳过", not ok and "没有 checks" in why, why)
ok, why = case_runnability({"kind": "api", "steps": [
    {"no": 1, "request": {"method": "GET", "path": "/"},
     "checks": [{"src": "status", "op": "eq", "value": 200}]}]})
check("kind=api 照旧可跑", ok and not why, why)
ok, why = case_runnability({"kind": "api", "steps": [
    {"no": 1, "action": "纯说明步骤", "expect": "x",
     "checks": [{"src": "status", "op": "eq", "value": 200}]}]})
check("既无 request 也无 ui 的步骤被拦", not ok and "既没" in why, why)

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
sys.exit(1 if fails else 0)
