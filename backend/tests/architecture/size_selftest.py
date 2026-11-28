"""size_rules.py 的零依赖自检。

不装 pytest 也能跑。CI 里在正式校验之前执行，
保证"门禁自己没坏"——门禁静默失效比没有门禁更危险。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import size_rules as size  # noqa: E402

FAILED: list[str] = []
PASSED: list[str] = []
_CASE_SEQ = [0]


@contextlib.contextmanager
def local_env():
    """临时清掉 CI 标记，模拟开发者本地环境。

    size_rules 在 CI 环境下拒绝 --update-budget（防止洗预算）。但自检必须能
    测到 --update-budget 本身的行为，否则在 CI 里自检会被自己的保护逻辑挡住。
    """
    saved = {k: os.environ.pop(k) for k in ("CI", "GITHUB_ACTIONS") if k in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fresh() -> Path:
    base = Path(tempfile.gettempdir()) / "size_gate_selftest"
    base.mkdir(parents=True, exist_ok=True)
    while True:
        _CASE_SEQ[0] += 1
        candidate = base / f"case{_CASE_SEQ[0]:03d}"
        if not candidate.exists():
            candidate.mkdir()
            return candidate


def make_repo(root: Path) -> Path:
    """一个最小可测仓库：2 个后端文件 + 1 个前端文件 + 1 个测试。"""
    write(
        root,
        "backend/app/api/v1/items.py",
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/projects')\n"
        "\n"
        "\n"
        "@router.get('/{pid}/items')\n"
        "def list_items(pid: str) -> dict:\n"
        "    return {'id': pid}\n"
        "\n"
        "\n"
        "@router.get('/{pid}/orphan')\n"
        "def orphan(pid: str) -> dict:\n"
        "    return {'id': pid}\n",
    )
    write(
        root,
        "backend/app/api/ingest/reads.py",
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/things')\n"
        "\n"
        "\n"
        "@router.get('/{tid}')\n"
        "def read_thing(tid: str) -> dict:\n"
        "    return {'id': tid}\n",
    )
    write(
        root,
        "backend/app/services/items.py",
        "def load_item(db, item_id):\n"
        "    return db.get(item_id)\n"
        "\n"
        "\n"
        "def list_items(db):\n"
        "    return []\n",
    )
    write(
        root,
        "frontend/src/services/api/items.ts",
        "import { fetchJson } from './client'\n"
        "\n"
        "export function listItems(pid: string) {\n"
        "  return fetchJson(`/projects/${pid}/items`)\n"
        "}\n",
    )
    write(
        root,
        "backend/tests/test_items.py",
        "def test_one() -> None:\n"
        "    assert True\n"
        "\n"
        "\n"
        "def test_two() -> None:\n"
        "    assert True\n",
    )
    write(
        root,
        "backend/scripts/manage.py",
        "def main() -> int:\n"
        "    return 0\n",
    )
    write(
        root,
        "backend/pytest_workbench/plugin.py",
        "def pytest_configure(config):\n"
        "    return None\n",
    )
    return root


# ---------------------------------------------------------------- 用例


def t_measure_counts() -> None:
    root = make_repo(_fresh())
    data = size.measure(root)
    m = data["metrics"]
    assert m["v1_endpoints"] == 2, f"v1 端点数应为 2，实得 {m['v1_endpoints']}"
    assert m["ingest_endpoints"] == 1, f"ingest 端点数应为 1，实得 {m['ingest_endpoints']}"
    # 公开函数：items 路由 2 个 + ingest 路由 1 个 + services 2 个 = 5
    assert m["public_functions"] == 5, f"公开函数应为 5，实得 {m['public_functions']}"
    assert m["test_files"] == 1, f"测试文件应为 1，实得 {m['test_files']}"
    assert m["test_functions"] == 2, f"测试函数应为 2，实得 {m['test_functions']}"


def t_endpoint_prefix_applied() -> None:
    root = make_repo(_fresh())
    eps = size.collect_endpoints(root / "backend", "app/api/v1")
    paths = {e.path for e in eps}
    assert "/projects/{pid}/items" in paths, f"router prefix 未拼接：{paths}"


def t_frontend_paths_normalized() -> None:
    root = make_repo(_fresh())
    used = size.frontend_paths(root / "frontend")
    assert "/projects/*/items" in used, f"模板串未归一化：{used}"


def t_unused_detected() -> None:
    root = make_repo(_fresh())
    data = size.measure(root)
    unused, _ = size.unused_endpoints(data, set())
    names = {e.func for e in unused}
    assert names == {"orphan"}, f"应只报 orphan，实得 {names}"


def t_allowlist_suppresses() -> None:
    root = make_repo(_fresh())
    data = size.measure(root)
    unused, stale = size.unused_endpoints(data, {"/projects/*/orphan"})
    assert not unused, f"允许清单未生效：{[e.func for e in unused]}"
    assert not stale, f"不应有失效条目：{stale}"


def t_stale_allowlist_reported() -> None:
    root = make_repo(_fresh())
    data = size.measure(root)
    _, stale = size.unused_endpoints(data, {"/projects/*/gone"})
    assert stale == ["/projects/*/gone"], f"失效条目未上报：{stale}"


def t_budget_blocks_growth() -> None:
    root = make_repo(_fresh())
    data = size.measure(root)
    tight = {k: v for k, v in data["metrics"].items()}
    tight["backend_app_loc"] = 1  # 故意设得很小
    problems = size.compare_with_budget(data, {"budget": tight})
    assert any(p.rule == "SIZE001" for p in problems), "体量超标未拦截"


def t_budget_allows_decrease() -> None:
    root = make_repo(_fresh())
    data = size.measure(root)
    # 测试项是"只允许增加"，所以放宽时不能动它们
    loose = {}
    for k, v in data["metrics"].items():
        loose[k] = v if k in size.MUST_NOT_DECREASE else v + 100
    problems = size.compare_with_budget(data, {"budget": loose})
    size_problems = [p for p in problems if p.rule.startswith("SIZE00")]
    assert not size_problems, f"删减被误拦：{size_problems}"


def t_test_deletion_blocked() -> None:
    """删测试不能算减量 —— 这是本门禁最容易被绕过的点。"""
    root = make_repo(_fresh())
    data = size.measure(root)
    limits = dict(data["metrics"])
    limits["test_files"] = 5  # 声称原本有 5 个
    problems = size.compare_with_budget(data, {"budget": limits})
    assert any(p.rule == "SIZE008" for p in problems), "删测试未被拦截"


def t_new_endpoint_blocked() -> None:
    root = make_repo(_fresh())
    data = size.measure(root)
    limits = dict(data["metrics"])
    limits["v1_endpoints"] = 1  # 声称原本只有 1 个
    problems = size.compare_with_budget(data, {"budget": limits})
    assert any(p.rule == "SIZE005" for p in problems), "新增端点未被拦截"


def t_update_budget_rejects_growth() -> None:
    root = make_repo(_fresh())
    budget = root / "size_budget.json"
    budget.write_text(
        json.dumps({"budget": {k: 0 for k in size.BUDGET_KEYS}}), encoding="utf-8"
    )
    before = budget.read_text(encoding="utf-8")
    with local_env():
        rc = size.main(["--root", str(root), "--budget", str(budget), "--update-budget"])
    assert rc == 1, f"调大预算应返回 1，实得 {rc}"
    assert budget.read_text(encoding="utf-8") == before, "被拒绝时不应改写预算文件"


def t_update_budget_allows_shrink() -> None:
    root = make_repo(_fresh())
    budget = root / "size_budget.json"
    # 宽松预算：生产项给大值，测试项给小值（测试只允许增加，小值代表"可以增长"）
    generous = {}
    for k in size.BUDGET_KEYS:
        generous[k] = 1 if k in size.MUST_NOT_DECREASE else 9999
    budget.write_text(json.dumps({"budget": generous}), encoding="utf-8")
    with local_env():
        rc = size.main(["--root", str(root), "--budget", str(budget), "--update-budget"])
    assert rc == 0, f"收紧预算应成功，实得 {rc}"
    after = json.loads(budget.read_text(encoding="utf-8"))
    assert after["budget"]["v1_endpoints"] == 2, "预算未按实测收紧"


def t_first_time_update_works() -> None:
    """首次接入时预算文件不存在，不能被"只许下调"挡住。"""
    root = make_repo(_fresh())
    budget = root / "size_budget.json"
    assert not budget.exists()
    with local_env():
        rc = size.main(["--root", str(root), "--budget", str(budget), "--update-budget"])
    assert rc == 0, f"首次生成预算应成功，实得 {rc}"
    assert budget.is_file(), "预算文件未生成"


def t_scripts_and_plugin_counted() -> None:
    """scripts/ 与 pytest_workbench/ 也属生产代码。

    只统计 backend/app 会留下绕过口子：在 scripts/ 里加功能不会触发任何预算项。
    实测在真实仓库中发生过（新增 258 行 manage.py 而门禁全绿）。
    """
    root = make_repo(_fresh())
    m = size.measure(root)["metrics"]
    # manage.py: "def main() -> int:" + "    return 0" = 2 行
    assert m["backend_scripts_loc"] == 2, f"scripts 行数应为 2，实得 {m['backend_scripts_loc']}"
    assert m["backend_plugin_loc"] == 2, f"plugin 行数应为 2，实得 {m['backend_plugin_loc']}"


def t_scripts_growth_blocked() -> None:
    root = make_repo(_fresh())
    data = size.measure(root)
    limits = dict(data["metrics"])
    limits["backend_scripts_loc"] = 0
    problems = size.compare_with_budget(data, {"budget": limits})
    assert any(p.rule == "SIZE012" for p in problems), "scripts 增长未被拦截"


def t_plugin_growth_blocked() -> None:
    root = make_repo(_fresh())
    data = size.measure(root)
    limits = dict(data["metrics"])
    limits["backend_plugin_loc"] = 0
    problems = size.compare_with_budget(data, {"budget": limits})
    assert any(p.rule == "SIZE013" for p in problems), "plugin 增长未被拦截"


def t_missing_budget_key_blocked() -> None:
    """删掉预算文件里的某个键 = 放弃该项约束，必须报错。"""
    root = make_repo(_fresh())
    data = size.measure(root)
    limits = dict(data["metrics"])
    limits.pop("backend_app_loc")
    problems = size.compare_with_budget(data, {"budget": limits})
    assert any(p.rule == "SIZE014" for p in problems), "缺失预算项未被拦截"


def t_missing_budget_file_blocked() -> None:
    root = make_repo(_fresh())
    data = size.measure(root)
    problems = size.compare_with_budget(data, {})
    assert any(p.rule == "SIZE014" for p in problems), "预算文件缺失未被拦截"


def t_new_budget_key_allowed() -> None:
    """门禁升级新增预算项时，不应被"只许下调"挡住。"""
    root = make_repo(_fresh())
    budget = root / "size_budget.json"
    metrics = size.measure(root)["metrics"]
    old = {k: v for k, v in metrics.items() if k not in ("backend_scripts_loc", "backend_plugin_loc")}
    budget.write_text(json.dumps({"budget": old}), encoding="utf-8")
    with local_env():
        rc = size.main(["--root", str(root), "--budget", str(budget), "--update-budget"])
    assert rc == 0, f"补齐新增预算项应成功，实得 {rc}"
    after = json.loads(budget.read_text(encoding="utf-8"))
    assert "backend_scripts_loc" in after["budget"], "新增项未写入"


def t_json_output_is_parseable() -> None:
    root = make_repo(_fresh())
    budget = root / "size_budget.json"
    with local_env():
        size.main(["--root", str(root), "--budget", str(budget), "--update-budget"])

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        size.main(["--root", str(root), "--budget", str(budget), "--json"])
    payload = json.loads(buf.getvalue())
    assert "metrics" in payload and "problems" in payload, "JSON 结构不完整"


# ---------------------------------------------------------------- 运行


def check(name: str, fn) -> None:
    try:
        fn()
    except AssertionError as exc:
        FAILED.append(f"{name}: {exc}")
    except Exception as exc:  # noqa: BLE001
        import traceback

        FAILED.append(f"{name}: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    else:
        PASSED.append(name)


def _cleanup() -> None:
    import shutil

    base = Path(tempfile.gettempdir()) / "size_gate_selftest"
    if base.is_dir():
        shutil.rmtree(base, ignore_errors=True)


def main() -> int:
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("t_") and callable(fn)
    ]
    for name, fn in tests:
        check(name, fn)

    _cleanup()

    # 自检用例数下限：把 t_ 改名或删掉用例会让自检"通过 0 / 0"并返回 0，
    # 那等于门禁被静默解除。宁可失败也不要假绿。
    MIN_CASES = 20
    if len(tests) < MIN_CASES:
        print(f"自检用例数 {len(tests)} < {MIN_CASES}，自检被削弱。")
        print("可执行用例：" + ", ".join(name for name, _ in tests))
        return 1

    print(f"通过 {len(PASSED)} / {len(tests)}")
    if FAILED:
        print("\n失败：")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    print("OK: 体量门禁自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
