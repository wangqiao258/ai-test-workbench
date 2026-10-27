"""用例锚点与去重：接口关联表同步、标题归一化、近似重复检测、响应装饰。"""

import difflib
import re

import json

from .generation import case_intent_fingerprint
from .steps import parse_steps
from .validation import parse_dims


def norm_title(text):
    """标题归一化：去掉空白与标点，用于近似重复判断。"""
    return re.sub(r"[\s\W_]+", "", text or "").lower()


def find_similar_case(conn, data, itf_id, module, threshold=0.85):
    """项目级查重：先比测试行为指纹，再保留标题相似度兜底。"""
    rows = conn.execute(
        "SELECT id, title, module, interface_id, doc_id, preconditions, steps, steps_json, "
        "expected, intent_fingerprint, dims FROM cases WHERE project_id=?",
        (data["project_id"],)).fetchall()
    links = {}
    for link in conn.execute(
            "SELECT ci.case_id, ci.interface_id FROM case_interfaces ci "
            "JOIN cases c ON c.id=ci.case_id WHERE c.project_id=?", (data["project_id"],)):
        links.setdefault(link["case_id"], []).append(link["interface_id"])
    candidate = {**data, "interface_id": itf_id, "module": module}
    candidate_ids = data.get("interface_ids") or ([itf_id] if itf_id else [])
    fingerprint = case_intent_fingerprint(candidate, candidate_ids)
    for row in rows:
        item = dict(row)
        existing = item.get("intent_fingerprint") or case_intent_fingerprint(
            item, links.get(item["id"]) or ([item["interface_id"]] if item["interface_id"] else []))
        if existing == fingerprint:
            item["duplicate_kind"] = "intent"
            return item
    target = norm_title(data["title"])
    best = None
    for row in rows:
        if row["title"] == data["title"]:
            item = dict(row)
            item["duplicate_kind"] = "title"
            return item
        score = difflib.SequenceMatcher(None, target, norm_title(row["title"])).ratio()
        if score >= threshold and (best is None or score > best[0]):
            best = (score, row)
    if not best:
        return None
    item = dict(best[1])
    item["duplicate_kind"] = "title"
    return item

def find_similar_bug(conn, project_id, title, threshold=0.85):
    """在项目范围内找标题高度相似的 Bug（提交前查重，2026-10-26 加）。

    起因：线上 57 投 55 驳，"同一问题换个标题再投一条"是常见驳回原因之一，
    而用例早就有 0.85 查重、Bug 一直没有——提交方（AI）在入口处就能看见
    "这条已经投过了"，比等 96.5% 的驳回率再反馈高效得多。
    返回最相似的既有 Bug（含它的分诊状态），由调用方决定是否 force。
    """
    rows = conn.execute(
        "SELECT id, title, review_status, reported_at FROM bugs WHERE project_id=?",
        (project_id,)).fetchall()
    target = norm_title(title)
    best = None
    for r in rows:
        if r["title"] == title:
            return r
        score = difflib.SequenceMatcher(None, target, norm_title(r["title"])).ratio()
        if score >= threshold and (best is None or score > best[0]):
            best = (score, r)
    return best[1] if best else None


def sync_case_links(conn, case_id, link_ids):
    """整体替换用例的接口关联。主锚点 interface_id 也必须在 link_ids 里。"""
    conn.execute("DELETE FROM case_interfaces WHERE case_id=?", (case_id,))
    for iid in dict.fromkeys(link_ids or []):
        conn.execute(
            "INSERT OR IGNORE INTO case_interfaces (case_id, interface_id) VALUES (?,?)",
            (case_id, iid))

def case_interface_ids(conn, case_id):
    return [r[0] for r in conn.execute(
        "SELECT interface_id FROM case_interfaces WHERE case_id=? ORDER BY interface_id",
        (case_id,))]

def decorate_case(row):
    """API 返回前把 JSON 字符串字段解析成原生数组/对象，方便 AI 直接消费。"""
    if "dims" in row:
        row["dims"] = parse_dims(row.get("dims"))
    if row.get("steps_json"):
        row["steps_json"] = parse_steps(row["steps_json"])
    return row

