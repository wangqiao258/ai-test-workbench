"""存量用例补锚点 + 覆盖维度（一次性迁移，幂等可重跑）。

原则：只在标题/预期能明确指向某个接口或某个页面文档时才写锚点，其余留空。
留空的用例仍然有 module（第三条锚点），不会被"无主"；下一次生成时 AI 通过
GET /api/coverage 能看到它们的标题，仍然不会重复。

用法：python scripts/backfill_anchors.py [--apply]
不带 --apply 只打印将要写入的内容（dry-run）。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

import db  # noqa: E402

# 用例 id -> 接口 id（依据标题明确指向，见 docs/当前设计说明.md）
INTERFACE_MAP = {
    4: 3,    # 错误密码登录的用户提示 -> 账号登录
    5: 3,    # 未携带 clientType 应校验验证码 -> 账号登录
    6: 3,    # clientType=h5 连续错误密码 -> 账号登录
    11: 12,  # 素材按名称搜索过滤 -> 素材分页(搜索)
    13: 15,  # 话术列表按业务线与场景筛选 -> 话术分页
    14: 31,  # 个人资料展示与字段校验 -> 当前用户信息
    15: 32,  # 修改密码表单校验 -> 修改密码
    17: 17,  # 会话存档必须校验员工参数 -> 会话消息分页
    22: 4,   # 刷新令牌参数位置与错误提示 -> 刷新令牌
}

# 用例 id -> 文档 id（页面/流程类，正文见 doc#2 侧边栏页面结构）
DOC_MAP = {
    8: 2,    # 工作台四个主 Tab 切换
    9: 2,    # 客户详情顶部信息卡片
    10: 2,   # 视频播放页签无权限提示
    16: 2,   # 应用设置主题色/字号
}

# 覆盖维度：只按标题里的明确信号打标，没有信号就留空（不臆测）
DIMS = {
    2: ["异常"], 3: ["边界"], 4: ["异常"], 5: ["异常", "鉴权"],
    6: ["安全", "异常"], 7: ["越权"], 8: ["正常"], 9: ["正常", "边界"],
    10: ["越权"], 11: ["正常", "边界"], 12: ["正常"], 13: ["正常"],
    14: ["正常", "边界"], 15: ["异常", "边界"], 16: ["正常"],
    17: ["鉴权", "越权"], 18: ["越权"], 19: ["鉴权"], 20: ["边界"],
    21: ["异常"], 22: ["异常", "兼容"], 23: ["安全"], 24: ["安全"],
    25: ["安全"], 42: ["正常", "兼容"], 47: ["正常"],
    # 已挂接口、但标题里没有关键词信号的，按预期内容人工判定
    35: ["鉴权", "越权"], 46: ["异常"], 55: ["异常", "边界"],
}
# 已挂接口的用例按标题补维度（关键词 -> 维度）
KEYWORD_DIMS = (
    (("异常", "错误", "失败", "500", "畸形", "不合法", "拒绝", "超时"), "异常"),
    (("边界", "上限", "下限", "空值", "极值", "越界", "分页"), "边界"),
    (("越权", "跨租户", "归属", "无权", "越权访问", "遍历"), "越权"),
    (("鉴权", "token", "Token", "未登录", "身份", "凭证", "401", "403"), "鉴权"),
    (("幂等", "重复提交"), "幂等"),
    (("并发", "同时"), "并发"),
    (("兼容", "分辨率", "浏览器", "版本"), "兼容"),
    (("性能", "耗时", "响应时间", "压测"), "性能"),
    (("安全", "CORS", "注入", "XSS", "CSRF", "硬编码", "泄露"), "安全"),
)


def infer_dims(title, expected):
    text = f"{title} {expected}"
    dims = [d for kws, d in KEYWORD_DIMS if any(k in text for k in kws)]
    return list(dict.fromkeys(dims))


def sync_linked_modules(conn, apply=False):
    """挂了接口的用例，module 必须等于接口的 module；原来的「接口回归-XX」挪进 batch。"""
    rows = conn.execute(
        "SELECT c.id, c.module cm, c.batch, i.module im FROM cases c "
        "JOIN interfaces i ON i.id=c.interface_id WHERE c.module<>i.module").fetchall()
    print(f"\n== module 与接口不一致的用例：{len(rows)} 条 ==")
    for r in rows:
        batch = r["batch"]
        if not batch and (r["cm"] or "").startswith("接口回归"):
            batch = r["cm"]                  # 批次信息不丢，从 module 挪到 batch
        print(f"  #{r['id']:>2} {r['cm'] or '(空)':<18} -> {r['im']:<14} batch={batch or '-'}")
        if apply:
            conn.execute("UPDATE cases SET module=?, batch=? WHERE id=?",
                         (r["im"], batch, r["id"]))
    return len(rows)


def main(apply=False):
    conn = db.get_db()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(cases)")]
    if not all(c in cols for c in ("doc_id", "dims")):
        print("缺少 doc_id/dims 列，请先启动一次 app.py 触发迁移")
        return 1
    rows = [dict(r) for r in conn.execute(
        "SELECT id, module, title, expected, interface_id, doc_id, dims FROM cases ORDER BY id")]
    changed = 0
    print(f"{'ID':>4} {'锚点':<26} {'维度':<18} 标题")
    for r in rows:
        itf = INTERFACE_MAP.get(r["id"])
        doc = DOC_MAP.get(r["id"])
        dims = DIMS.get(r["id"]) or infer_dims(r["title"], r["expected"])
        if r["interface_id"]:
            itf = r["interface_id"]
        new_dims = json.dumps(dims, ensure_ascii=False) if dims else ""
        anchor = (f"interface#{itf}" if itf else (f"doc#{doc}" if doc else f"module:{r['module']}"))
        print(f"{r['id']:>4} {anchor:<26} {','.join(dims) or '-':<18} {r['title'][:34]}")
        if apply:
            sets, args = [], []
            if itf and not r["interface_id"]:
                im = conn.execute("SELECT module FROM interfaces WHERE id=?", (itf,)).fetchone()
                sets += ["interface_id=?", "module=?"]
                args += [itf, im["module"] if im else r["module"]]
            if doc and not r["doc_id"]:
                sets.append("doc_id=?")
                args.append(doc)
            if new_dims != (r["dims"] or ""):
                sets.append("dims=?")
                args.append(new_dims)
            if sets:
                args.append(r["id"])
                conn.execute(f"UPDATE cases SET {', '.join(sets)} WHERE id=?", args)
                changed += 1
    if apply:
        conn.commit()
        print(f"\n已写入 {changed} 条")
    else:
        print("\n（dry-run，未写库；加 --apply 执行）")
    sync_linked_modules(conn, apply)
    if apply:
        conn.commit()
    # 汇总
    stat = conn.execute(
        "SELECT COUNT(*) total, SUM(interface_id IS NOT NULL) itf, SUM(doc_id IS NOT NULL) doc,"
        " SUM(interface_id IS NULL AND doc_id IS NULL) only_module,"
        " SUM(dims <> '') with_dims FROM cases").fetchone()
    print("统计：总数={total} 挂接口={itf} 挂文档={doc} 仅挂模块={only_module} 有维度={with_dims}"
          .format(**stats_to_dict(stat)))
    conn.close()
    return 0


def stats_to_dict(row):
    return dict(row)


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
