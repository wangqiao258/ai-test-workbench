"""core/filters.py 的纯函数单测：不连库、不启服务。

用法（在 ai-test-platform 目录下）：
    python tests/test_filters.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.filters import (Field, build, clean_qs, escape_like,  # noqa: E402
                          paginate, qs_with)

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


class Args(dict):
    """模拟 request.args 的 .get()。"""

    def get(self, key, default=None):
        return dict.get(self, key, default)

    def items(self):
        return dict.items(self)


SPEC = (
    Field("module", "eq", col="module", vocab=("认证", "系统"), label="模块"),
    Field("dim", "like", col="dims", vocab=("异常", "边界"), label="覆盖维度"),
    Field("q", "like_multi", cols=("title", "path"), label="关键字"),
    Field("b_status", "map", default="active", label="状态", mapping=(
        ("active", "status IN ('open','fixed')", ()),
        ("all", "1=1", ()),
        ("closed", "status=?", ("closed",)),
    )),
)

print("== 1. eq / 词表 ==")
r = build(SPEC, Args())
check("空参数时 eq 字段不出条件", r["where"] == ["(status IN ('open','fixed'))"], r["where"])
check("默认 map 不算已筛选", r["active"] == [] and r["state"]["b_status"] == "active")

r = build(SPEC, Args(module="认证"))
check("模块命中出 module=?", r["where"] == ["module=?", "(status IN ('open','fixed'))"], r["where"])
check("模块值进 params", r["params"] == ["认证"], r["params"])
check("模块记入 active", r["active"] == ["模块"], r["active"])

r = build(SPEC, Args(module="不存在的模块"))
check("词表外的值直接忽略", "module=?" not in r["where"] and r["state"]["module"] == "")

print("\n== 2. like / like_multi / 转义 ==")
check("escape_like 转义三个字符",
      escape_like("50%_a\\b") == "50\\%\\_a\\\\b", escape_like("50%_a\\b"))

r = build(SPEC, Args(dim="异常"))
check("like 生成 ESCAPE 子句", r["where"][0] == "dims LIKE ? ESCAPE '\\'", r["where"][0])
check("like 两侧加通配符", r["params"] == ["%异常%"], r["params"])

r = build(SPEC, Args(q="a%b"))
check("关键字走多列 OR", r["where"][0] == "(title LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\')",
      r["where"][0])
check("关键字参数按列数复制且已转义", r["params"] == ["%a\\%b%", "%a\\%b%"], r["params"])

r = build(SPEC, Args(dim="不存在"))
check("like 词表外忽略", not r["where"] or "dims" not in r["where"][0])

print("\n== 3. map 语义 ==")
r = build(SPEC, Args(b_status="closed"))
check("map 命中用参数化", r["where"][-1] == "(status=?)" and r["params"] == ["closed"], r["params"])
check("非默认值记入 active", r["active"] == ["状态"], r["active"])

r = build(SPEC, Args(b_status="all"))
check("all 不产生条件", r["where"] == [], r["where"])
check("all 仍回填 state", r["state"]["b_status"] == "all")

r = build(SPEC, Args(b_status="乱填"))
check("map 未命中回落到默认", r["state"]["b_status"] == "active"
      and r["where"] == ["(status IN ('open','fixed'))"])

print("\n== 4. 分页 ==")
p = paginate(0, 1, 50)
check("0 条时仍算 1 页且 start=0", p["pages"] == 1 and p["start"] == 0 and p["total"] == 0)

p = paginate(161, 2, 50)
check("第 2 页窗口正确", (p["page"], p["offset"], p["start"], p["end"]) == (2, 50, 51, 100), p)

p = paginate(161, 99, 50)
check("超大页码钳到末页", (p["page"], p["pages"], p["end"]) == (4, 4, 161), p)

p = paginate(161, -3, 50)
check("负数页码回到第 1 页", p["page"] == 1)

p = paginate(161, "abc", 50)
check("非数字页码回到第 1 页", p["page"] == 1)

p = paginate(100, 2, 50)
check("整除时页数不多算", p["pages"] == 2, p["pages"])

print("\n== 5. back 白名单与查询串 ==")
check("只保留白名单键",
      clean_qs("tab=cases&module=x&evil=http://a&page=2") == "tab=cases&module=x&page=2",
      clean_qs("tab=cases&module=x&evil=http://a&page=2"))
check("空 back 返回空", clean_qs("") == "" and clean_qs(None) == "")
check("javascript: 伪协议进不来", clean_qs("tab=javascript:alert(1)") == "tab=javascript%3Aalert%281%29",
      clean_qs("tab=javascript:alert(1)"))

check("qs_with 删掉空参数",
      qs_with(Args(tab="interfaces", page="2", module="认证"), page="") == "tab=interfaces&module=%E8%AE%A4%E8%AF%81",
      qs_with(Args(tab="interfaces", page="2", module="认证"), page=""))
check("qs_with 覆盖参数", qs_with(Args(tab="cases"), page=3) == "tab=cases&page=3")

print("\n== 6. Field 自检 ==")
for bad, why in [
    (lambda: Field("x", "eq"), "eq 缺 col"),
    (lambda: Field("x", "like_multi"), "like_multi 缺 cols"),
    (lambda: Field("x", "map"), "map 缺 mapping"),
    (lambda: Field("x", "nope", col="c"), "未知类型"),
]:
    try:
        bad()
        check(f"非法 Field 被拒（{why}）", False)
    except ValueError:
        check(f"非法 Field 被拒（{why}）", True)

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
sys.exit(1 if fails else 0)
