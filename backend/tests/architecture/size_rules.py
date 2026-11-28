"""减法门禁：代码体量与功能面只允许下降，不允许增长。

与 arch_rules.py 的分工：
- arch_rules.py 管"结构是否正确"（分层、重复、契约漂移）
- size_rules.py 管"体量是否在缩小"（行数、文件数、端点数、公开函数数）

核心是预算棘轮：size_budget.json 记录当前体量，实际值不得超过它。
删除永远被允许；增长一律失败。这样重构可以放开手删，
但删掉的东西不会以"新功能"的名义长回来。

用法（仓库根目录）：
    python backend/tests/architecture/size_rules.py --root . --budget backend/size_budget.json
    python backend/tests/architecture/size_rules.py --root . --budget backend/size_budget.json --json
    python backend/tests/architecture/size_rules.py --root . --budget backend/size_budget.json --update-budget
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 预算项 -> (规则号, 说明)
BUDGET_KEYS: dict[str, tuple[str, str]] = {
    "backend_app_loc": ("SIZE001", "backend/app 生产代码行数"),
    "backend_app_files": ("SIZE002", "backend/app 生产代码文件数"),
    "frontend_src_loc": ("SIZE003", "frontend/src 代码行数（.ts/.tsx）"),
    "frontend_styles_loc": ("SIZE004", "frontend/src 样式行数（.css）"),
    "v1_endpoints": ("SIZE005", "/api/v1 端点数量"),
    "ingest_endpoints": ("SIZE006", "/ingest/v1 端点数量"),
    "public_functions": ("SIZE007", "backend/app 模块级公开函数数量"),
    # 反向保护：测试只允许增加。删测试不能算作"减量"，
    # 否则可以用删掉安全网的方式让体量指标变好看。
    "test_files": ("SIZE008", "测试文件数量（只允许增加）"),
    "test_functions": ("SIZE009", "测试函数数量（只允许增加）"),
}

# 这几项是"只能增不能减"，判定方向相反
MUST_NOT_DECREASE = {"test_files", "test_functions"}

_SKIP_DIRS = {
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "alembic",
    ".git",
    "dist",
    "build",
}


# ---------------------------------------------------------------- 基础工具


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return None


def _walk(root: Path, suffixes: tuple[str, ...]):
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if set(path.parts) & _SKIP_DIRS:
            continue
        yield path


def _count_lines(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 0


def _locate(root: Path) -> tuple[Path, Path]:
    """定位 (backend, frontend)。root 可以是仓库根，也可以是 backend 根。"""
    if (root / "backend" / "app").is_dir():
        return root / "backend", root / "frontend"
    if (root / "app").is_dir():
        return root, root.parent / "frontend"
    return root / "backend", root / "frontend"


# ---------------------------------------------------------------- 端点采集


@dataclass
class Endpoint:
    method: str
    path: str
    func: str
    file: str
    line: int


def _router_prefix(tree: ast.Module) -> str:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id == "router"):
                continue
            if isinstance(node.value, ast.Call):
                for kw in node.value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        return str(kw.value.value)
    return ""


def _route_method(deco: ast.AST) -> str | None:
    if not isinstance(deco, ast.Call):
        return None
    func = deco.func
    if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
        return None
    if func.value.id != "router":
        return None
    return func.attr.upper()


def collect_endpoints(backend: Path, sub: str) -> list[Endpoint]:
    out: list[Endpoint] = []
    base = backend / sub
    if not base.is_dir():
        return out
    for path in sorted(base.rglob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        prefix = _router_prefix(tree)
        rel = path.relative_to(backend).as_posix()
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                method = _route_method(deco)
                if method is None:
                    continue
                route = ""
                if deco.args and isinstance(deco.args[0], ast.Constant):
                    route = str(deco.args[0].value)
                out.append(Endpoint(method, prefix + route, node.name, rel, node.lineno))
    return out


# ---------------------------------------------------------------- 前端调用


# 前端取数函数。新增取数封装时需同步这里，否则会误报"端点无人调用"。
_CALL_RE = re.compile(
    r"(?:request|fetchJson|fetchAllPages)\s*(?:<[^>]*>)?\s*\(\s*[`'\"]([^`'\"]+)[`'\"]"
)


def normalize_path(path: str) -> str:
    """把前端模板串与后端路由模板统一成同一形状。

    /projects/${id}/runs  ->  /projects/*/runs
    /projects/{id}/runs   ->  /projects/*/runs
    /projects/*/runs?x=1  ->  /projects/*/runs
    """
    path = re.sub(r"\$\{[^}]*\}", "*", path)
    path = re.sub(r"\{[^}]+\}", "*", path)
    return path.split("?")[0].rstrip("/")


def frontend_paths(frontend: Path) -> set[str]:
    out: set[str] = set()
    for path in _walk(frontend / "src", (".ts", ".tsx")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for raw in _CALL_RE.findall(text):
            out.add(normalize_path(raw))
    return out


# ---------------------------------------------------------------- 体量测量


def measure(root: Path) -> dict:
    backend, frontend = _locate(root)
    app = backend / "app"

    app_files = list(_walk(app, (".py",)))
    ts_files = list(_walk(frontend / "src", (".ts", ".tsx")))
    css_files = list(_walk(frontend / "src", (".css",)))

    public_functions = 0
    for path in app_files:
        tree = _parse(path)
        if tree is None:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("_"):
                public_functions += 1

    v1 = collect_endpoints(backend, "app/api/v1")
    ingest = collect_endpoints(backend, "app/api/ingest")

    # 测试规模：用来防止"删测试换减量"
    test_files = list((backend / "tests").rglob("test_*.py"))
    test_functions = 0
    for path in test_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        test_functions += len(re.findall(r"^\s*def test_", text, re.M))

    metrics = {
        "backend_app_loc": sum(_count_lines(p) for p in app_files),
        "backend_app_files": len(app_files),
        "frontend_src_loc": sum(_count_lines(p) for p in ts_files),
        "frontend_styles_loc": sum(_count_lines(p) for p in css_files),
        "v1_endpoints": len(v1),
        "ingest_endpoints": len(ingest),
        "public_functions": public_functions,
        "test_files": len(test_files),
        "test_functions": test_functions,
    }
    return {
        "metrics": metrics,
        "v1": v1,
        "ingest": ingest,
        "frontend_paths": frontend_paths(frontend),
    }


# ---------------------------------------------------------------- 判定


@dataclass
class Problem:
    rule: str
    message: str
    hint: str = ""


def unused_endpoints(data: dict, allow: set[str]) -> tuple[list[Endpoint], list[str]]:
    """返回 (无人调用的端点, 已失效的允许清单条目)。

    只看 /api/v1：ingest 面是给 AI agent 的外部契约，前端本就不该调用。
    """
    used = data["frontend_paths"]
    unused: list[Endpoint] = []
    alive: set[str] = set()
    for ep in data["v1"]:
        key = normalize_path(ep.path)
        alive.add(key)
        if key in used or key in allow:
            continue
        unused.append(ep)
    stale = sorted(allow - alive)
    return unused, stale


def compare_with_budget(data: dict, budget: dict) -> list[Problem]:
    problems: list[Problem] = []
    limits = budget.get("budget", {})
    metrics = data["metrics"]

    for key, (rule, label) in BUDGET_KEYS.items():
        limit = limits.get(key)
        if limit is None:
            continue
        actual = metrics.get(key, 0)
        if key in MUST_NOT_DECREASE:
            # 测试规模：只允许增加
            if actual < limit:
                problems.append(
                    Problem(
                        rule,
                        f"{label} {actual} < 下限 {limit}（少了 {limit - actual}）",
                        "测试只允许增加。删测试不能算作代码减量。",
                    )
                )
            continue
        if actual > limit:
            problems.append(
                Problem(
                    rule,
                    f"{label} {actual} > 预算 {limit}（超出 {actual - limit}）",
                    "只允许下降。若确实需要新增，先在别处删掉等量代码。",
                )
            )

    unused, stale = unused_endpoints(data, set(budget.get("unused_endpoints", [])))
    for ep in unused:
        problems.append(
            Problem(
                "SIZE010",
                f"新增端点无人调用：{ep.method} {ep.path}（{ep.file}:{ep.line} {ep.func}）",
                "前端未引用。若供外部/AI 调用，请加入 size_budget.json 的 unused_endpoints。",
            )
        )
    for key in stale:
        problems.append(
            Problem(
                "SIZE011",
                f"允许清单条目已失效：{key}",
                "该端点已不存在，请从 size_budget.json 的 unused_endpoints 中删除这一行。",
            )
        )
    return problems


# ---------------------------------------------------------------- 主流程


def load_budget(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="体量预算检查（只允许下降）")
    parser.add_argument("--root", default=".")
    parser.add_argument("--budget", default="backend/size_budget.json")
    parser.add_argument("--update-budget", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    budget_path = Path(args.budget)
    if not budget_path.is_absolute():
        budget_path = root / budget_path

    data = measure(root)
    metrics = data["metrics"]

    if args.update_budget:
        first_time = not budget_path.is_file()
        old = load_budget(budget_path)
        old_limits = old.get("budget", {})
        grew = {}
        shrank_bad = {}
        for key, value in metrics.items():
            before = old_limits.get(key, 0)
            if key in MUST_NOT_DECREASE:
                if value < before:
                    shrank_bad[key] = (before, value)
            elif value > before:
                grew[key] = (before, value)
        if (grew or shrank_bad) and not first_time:
            if grew:
                print("拒绝写入：以下预算项被调大。预算只允许下调。")
                for key, (before, after) in sorted(grew.items()):
                    rule, label = BUDGET_KEYS.get(key, ("SIZE000", key))
                    print(f"  {rule} {label}: {before} -> {after}")
            if shrank_bad:
                print("拒绝写入：以下测试规模被缩小。测试只允许增加。")
                for key, (before, after) in sorted(shrank_bad.items()):
                    rule, label = BUDGET_KEYS.get(key, ("SIZE000", key))
                    print(f"  {rule} {label}: {before} -> {after}")
            print("\n请先把体量真正降下来，再执行 --update-budget。")
            return 1
        unused, _ = unused_endpoints(data, set())
        payload = {
            "version": 1,
            "note": "体量预算只能下调。删除代码后执行 --update-budget 收紧；禁止调大。",
            "budget": metrics,
            "unused_endpoints": sorted(normalize_path(ep.path) for ep in unused),
        }
        budget_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"budget written -> {budget_path}")
        return 0

    budget = load_budget(budget_path)
    problems = compare_with_budget(data, budget)

    if args.json:
        print(
            json.dumps(
                {
                    "metrics": metrics,
                    "budget": budget.get("budget", {}),
                    "problems": [p.__dict__ for p in problems],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if problems else 0

    print("== 体量预算 ==")
    limits = budget.get("budget", {})
    for key, (rule, label) in BUDGET_KEYS.items():
        actual = metrics.get(key, 0)
        limit = limits.get(key)
        if limit is None:
            print(f"  {rule} {label:<32} {actual:>6}  （未设预算）")
            continue
        delta = actual - limit
        if key in MUST_NOT_DECREASE:
            if delta < 0:
                mark = f"  ↓ 少了 {-delta}  ← 测试不允许减少"
            else:
                mark = f"  ↑ 增加 {delta}" if delta > 0 else ""
        else:
            mark = "" if delta <= 0 else f"  ↑ 超预算 {delta}"
            if delta < 0:
                mark = f"  ↓ 已减 {-delta}"
        print(f"  {rule} {label:<32} {actual:>6}  (预算 {limit}){mark}")

    total_actual = metrics["backend_app_loc"] + metrics["frontend_src_loc"]
    total_actual += metrics["frontend_styles_loc"]
    print(f"\n  生产代码总量: {total_actual} 行")

    if problems:
        print("\n== 体量门禁失败 ==")
        for item in problems:
            print(f"  [{item.rule}] {item.message}")
            if item.hint:
                print(f"         {item.hint}")
        return 1

    print("\nOK: 体量未增长")
    return 0


if __name__ == "__main__":
    sys.exit(main())
