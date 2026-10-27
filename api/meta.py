"""连通性与手册。"""

import os

from flask import g, jsonify, request

from . import api_bp

from .deps import token_required

from db import now

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 手册查找顺序：仓库内真相源优先；data/ 供运维不动镜像就替换；最后是本地开发的 skill 目录兜底。
GUIDE_CANDIDATES = (
    os.path.join(ROOT, "docs", "ai_guide.md"),
    os.path.join(ROOT, "data", "ai_guide.md"),
    os.path.join(
        os.path.expanduser("~"), ".workbuddy", "skills",
        "ai-test-platform", "references", "api_reference.md",
    ),
)

# 参考手册（接口字典、用例、Bug、runs、错误码…）：开场不读，按需取。
# 拆开是为了控制开场 token：主手册 ~5k 字符，参考手册 ~24k，混在一起时每轮都会想整篇读。
REFERENCE_CANDIDATES = (
    os.path.join(ROOT, "docs", "ai_guide_reference.md"),
    os.path.join(ROOT, "data", "ai_guide_reference.md"),
)


def _first_file(candidates):
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None


def _guide_path(part=""):
    """返回实际存在的手册路径；都不存在返回 None。part=reference 取参考手册。"""
    forced = os.environ.get("APP_GUIDE_PATH", "").strip()
    if forced and part in ("", "main"):
        return forced if os.path.isfile(forced) else None
    if part == "reference":
        return _first_file(REFERENCE_CANDIDATES)
    return _first_file(GUIDE_CANDIDATES)


@api_bp.route("/ping")
@token_required
def api_ping():
    return jsonify({"ok": True, "actor": g.actor, "time": now()})


@api_bp.route("/guide")
@token_required
def api_guide():
    """默认返回开场手册；`?part=reference` 返回接口字典等细节（按需取，开场不要读）。"""
    part = (request.args.get("part") or "").strip().lower()
    if part == "main":
        part = ""
    if part not in ("", "reference"):
        return jsonify({"error": "part 只能是 reference",
                        "hint": "不带 part 取开场手册"}), 400
    path = _guide_path(part)
    if not path:
        return jsonify({
            "error": "guide not found",
            "part": part or "main",
            "searched": list(REFERENCE_CANDIDATES if part == "reference"
                             else GUIDE_CANDIDATES),
            "hint": "把 docs/ai_guide*.md 打进镜像，或用 APP_GUIDE_PATH 指定绝对路径",
        }), 503
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return jsonify({"guide": text, "part": part or "main", "path": path,
                    "chars": len(text)})
