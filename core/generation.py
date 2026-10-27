"""AI 持续生成的纯规则：策略词表、测试意图指纹与目标反馈状态。"""
import hashlib
import json
import re

STRATEGIES = (
    "breadth", "interface_depth", "flow", "data_state",
    "failure_driven", "change_driven",
)
TARGET_STATUSES = ("open", "claimed", "generated", "covered", "blocked", "deferred")
TARGET_PRIORITIES = ("P0", "P1", "P2", "P3")
FEEDBACK_OUTCOMES = ("duplicate", "invalid", "deferred", "reopen")


def norm_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_strategy(value, allow_empty=False):
    strategy = norm_text(value).lower().replace(" ", "_")
    if not strategy and allow_empty:
        return "", None
    if strategy not in STRATEGIES:
        return None, f"strategy 只能是 {'/'.join(STRATEGIES)} 之一"
    return strategy, None


def _canonical(value):
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, str):
        return norm_text(value)
    return value


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def target_fingerprint(data):
    """同一来源、同一测试意图只登记一次；标题措辞不参与指纹。"""
    return _digest({
        "interface_id": data.get("interface_id"),
        "doc_id": data.get("doc_id"),
        "parent_target_id": data.get("parent_target_id"),
        "module": norm_text(data.get("module")).lower(),
        "source_ref": norm_text(data.get("source_ref")).lower(),
        "intent": norm_text(data.get("intent")).lower(),
    })


def case_intent_fingerprint(case, interface_ids=None):
    """按测试行为而非标题查重；不同输入、前置状态和断言仍是不同用例。"""
    struct = case.get("steps_json")
    if isinstance(struct, str):
        try:
            struct = json.loads(struct) if struct else {}
        except (TypeError, ValueError):
            struct = {}
    steps, has_checks = [], False
    if isinstance(struct, dict) and isinstance(struct.get("steps"), list):
        for step in struct["steps"]:
            if not isinstance(step, dict):
                continue
            item = {}
            for key in ("request", "ui"):
                if step.get(key):
                    item[key] = _canonical(step[key])
            checks = step.get("checks") or []
            if checks:
                has_checks = True
                item["checks"] = _canonical(checks)
            else:
                item["expect"] = norm_text(step.get("expect")).lower()
            steps.append(item)
        kind = struct.get("kind") or "mixed"
    else:
        steps = norm_text(case.get("steps")).lower()
        kind = "text"
    ids = interface_ids if interface_ids is not None else [case.get("interface_id")]
    ids = sorted({int(v) for v in (ids or []) if v not in (None, "")})
    return _digest({
        "interface_ids": ids,
        "doc_id": case.get("doc_id"),
        "module": "" if ids else norm_text(case.get("module")).lower(),
        "preconditions": norm_text(case.get("preconditions")).lower(),
        "kind": kind,
        "steps": steps,
        "expected": "" if has_checks else norm_text(case.get("expected")).lower(),
    })


def target_execution_state(results):
    """失败优先于阻塞；目标下还有未执行用例时不能提前标记覆盖。"""
    results = list(results)
    if not results:
        return "generated", ""
    if "fail" in results:
        return "generated", "fail"
    if "blocked" in results:
        return "blocked", "blocked"
    if all(r == "pass" for r in results):
        return "covered", "pass"
    return "generated", ""
