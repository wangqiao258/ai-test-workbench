"""断言引擎纯函数单测：不连库、不起 Flask。

用法：python tests/test_asserts.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.asserts import (SRCS_API, evaluate, get_path, normalize_checks,  # noqa: E402
                          parse_path)
from core.steps import normalize_steps, render_steps  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond:
        fails.append(name)


CTX = {
    "status": 200,
    "headers": {"Content-Type": "application/json;charset=UTF-8", "X-Trace": "abc"},
    "body": '{"code":0,"msg":"ok","data":{"accessToken":"tk","list":[{"id":7}],'
            '"count":3,"empty":null}}',
    "duration_ms": 120,
}


def one(chk, ctx=None):
    return evaluate([chk], ctx or CTX)


print("== path 解析 ==")
check("$ 开头", parse_path("$.a.b") == ["a", "b"])
check("数组下标", parse_path("$.a[0].b") == ["a", 0, "b"])
check("裸路径", parse_path("a.b") == ["a", "b"])
check("空路径", parse_path("") == [] and parse_path("$") == [])
check("get_path 取到", get_path({"a": [1, 2]}, ["a", 1]) == (True, 2))
check("get_path 越界", get_path({"a": [1]}, ["a", 3]) == (False, None))
check("get_path 类型不符", get_path({"a": 1}, ["a", "b"]) == (False, None))

print("\n== 运算符 ==")
check("eq 命中", one({"src": "status", "op": "eq", "value": 200})[0])
check("eq 未命中", not one({"src": "status", "op": "eq", "value": 500})[0])
check("ne 命中", one({"src": "body", "path": "$.code", "op": "ne", "value": 1})[0])
check("ne 未命中", not one({"src": "body", "path": "$.code", "op": "ne", "value": 0})[0])
check("contains 字符串", one({"src": "body", "op": "contains", "value": "accessToken"})[0])
check("contains 不命中", not one({"src": "body", "op": "contains", "value": "refused"})[0])
check("not_contains 命中", one({"src": "body", "op": "not_contains", "value": "error"})[0])
check("not_contains 未命中", not one({"src": "body", "op": "not_contains", "value": "ok"})[0])
check("present 命中", one({"src": "body", "path": "$.data.accessToken", "op": "present"})[0])
check("present 值为 null 不算", not one({"src": "body", "path": "$.data.empty", "op": "present"})[0])
check("absent 字段不存在", one({"src": "body", "path": "$.data.nope", "op": "absent"})[0])
check("absent 值为 null 也算", one({"src": "body", "path": "$.data.empty", "op": "absent"})[0])
check("absent 字段存在且非空则失败",
      not one({"src": "body", "path": "$.code", "op": "absent"})[0])
check("gt 命中", one({"src": "body", "path": "$.data.count", "op": "gt", "value": 2})[0])
check("gt 未命中", not one({"src": "body", "path": "$.data.count", "op": "gt", "value": 9})[0])
check("lt 命中", one({"src": "duration_ms", "op": "lt", "value": 800})[0])
check("in 命中", one({"src": "body", "path": "$.code", "op": "in", "value": [0, 1]})[0])
check("in 未命中", not one({"src": "body", "path": "$.code", "op": "in", "value": [2, 3]})[0])
check("regex 命中", one({"src": "body", "op": "regex", "value": "access\\w+"})[0])
check("regex 未命中", not one({"src": "body", "op": "regex", "value": "^ERR"})[0])
check("数组下标取值", one({"src": "body", "path": "$.data.list[0].id", "op": "eq", "value": 7})[0])

print("\n== 响应头与类型边界 ==")
check("响应头大小写不敏感",
      one({"src": "headers", "path": "content-type", "op": "contains", "value": "json"})[0])
check("响应头自定义键",
      one({"src": "headers", "path": "x-trace", "op": "eq", "value": "abc"})[0])
check("按字段取但响应非 JSON 应失败",
      not one({"src": "body", "path": "$.code", "op": "eq", "value": 0},
              {"status": 200, "headers": {}, "body": "<html>oops</html>",
               "duration_ms": 5})[0])
check("非 JSON 全文 contains 可用",
      one({"src": "body", "op": "contains", "value": "oops"},
          {"status": 200, "headers": {}, "body": "<html>oops</html>",
           "duration_ms": 5})[0])
check("字段不存在时 eq 失败",
      not one({"src": "body", "path": "$.data.nope", "op": "eq", "value": 0})[0])
check("gt 遇非数字失败",
      not one({"src": "body", "path": "$.msg", "op": "gt", "value": 1})[0])

print("\n== 多条与失败描述 ==")
ok, why = evaluate([
    {"src": "status", "op": "eq", "value": 200},
    {"src": "body", "path": "$.code", "op": "ne", "value": 0},
], CTX)
check("多条里有一条失败即整体失败", ok is False and len(why) == 1, str(why))
check("失败描述带实际值", "实际 0" in why[0], why[0])
check("空 checks 不判通过", evaluate([], CTX)[0] is False)

print("\n== checks 规范化 ==")
norm, err = normalize_checks([{"src": "status", "op": "eq", "value": 200}])
check("合法 checks 通过", err is None and norm[0]["value"] == 200)
check("缺 value 被拒",
      normalize_checks([{"src": "status", "op": "eq"}])[1] is not None)
check("present 不需要 value",
      normalize_checks([{"src": "body", "path": "$.a", "op": "present"}])[1] is None)
check("非法 src 被拒",
      normalize_checks([{"src": "cookie", "op": "eq", "value": 1}])[1] is not None)
check("非法 op 被拒",
      normalize_checks([{"src": "status", "op": "startswith", "value": 2}])[1] is not None)
check("正则非法被拦",
      normalize_checks([{"src": "body", "op": "regex", "value": "([a"}])[1] is not None)
check("空数组视为没有断言",
      normalize_checks([])[0] == [] and normalize_checks(None)[0] == [])
check("非数组被拒", normalize_checks({"src": "status"})[1] is not None)

print("\n== 与 steps 校验的衔接 ==")
struct, err = normalize_steps({"kind": "api", "steps": [
    {"action": "探活", "request": {"method": "GET", "path": "/ping"}, "expect": "200",
     "checks": [{"src": "status", "op": "eq", "value": 200}]}]})
check("steps_json 接受 checks", err is None and struct["steps"][0]["checks"][0]["op"] == "eq")
check("渲染文本带断言数", "断言: 1 条" in render_steps(struct))
bad, err = normalize_steps({"kind": "api", "steps": [
    {"action": "探活", "request": {"method": "GET", "path": "/ping"}, "expect": "200",
     "checks": [{"src": "status", "op": "wat", "value": 1}]}]})
check("steps_json 拦截非法 checks", bad is None and "op 非法" in err, str(err))

print("\n== UI 页面快照断言（P2）==")
SNAP = {"url": "https://x.test/pages/index/index", "title": "待办",
        "text": "待办 全部 已完成", "elements": {"登录": "登录"}}
check("url contains", evaluate([{"src": "url", "op": "contains",
                                "value": "/index"}], SNAP)[0])
check("title eq", evaluate([{"src": "title", "op": "eq", "value": "待办"}], SNAP)[0])
check("text contains", evaluate([{"src": "text", "op": "contains",
                                  "value": "已完成"}], SNAP)[0])
check("text regex", evaluate([{"src": "text", "op": "regex", "value": "待办.*已"}], SNAP)[0])
check("element present", evaluate([{"src": "element", "path": "登录",
                                    "op": "present"}], SNAP)[0])
check("element 文本判定", evaluate([{"src": "element", "path": "登录", "op": "eq",
                                     "value": "登录"}], SNAP)[0])
check("快照里没有的元素：absent 通过",
      evaluate([{"src": "element", "path": "注册", "op": "absent"}], SNAP)[0])
check("快照里没有的元素：present 失败",
      not evaluate([{"src": "element", "path": "注册", "op": "present"}], SNAP)[0])
check("缺 url 时该条判失败",
      not evaluate([{"src": "url", "op": "contains", "value": "/x"}], {"text": ""})[0])
check("API 上下文不收页面断言",
      normalize_checks([{"src": "url", "op": "eq", "value": "x"}], 1, SRCS_API)[1]
      is not None)

print(f"\n{'全部通过' if not fails else '失败 %d 项：%s' % (len(fails), fails)}")
sys.exit(1 if fails else 0)
