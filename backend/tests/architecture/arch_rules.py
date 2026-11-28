"""架构约束检查器：用可执行断言守住模块边界。

设计要点（决定了它能否识别"假修复"）：

1. 纯 AST 分析，不 import 被测代码，不需要装项目依赖，秒级完成。
2. 重复代码检测是**全仓扫描 + AST 归一化指纹**：
   - 改函数名、改局部变量名、挪到第三个文件 —— 都无法绕过。
   - 只有真正合并成一处，数量才会下降。
3. 基线棘轮（ratchet）：arch_baseline.json 记录当前违规数，CI 要求
   实际数 <= 基线数。基线本身只允许调小；调大会被 ARCH900 拦下。
4. 抑制注释必须带理由和到期日，且数量同样受棘轮约束，
   防止用 `# arch: ignore` 批量消音。

用法：
    python -m tests.architecture.arch_rules --root . --baseline arch_baseline.json
    python -m tests.architecture.arch_rules --root . --update-baseline   # 仅修复后收紧用
"""

from __future__ import annotations

import argparse
import ast
import copy
import datetime
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_TODAY = datetime.date.today().isoformat()

# ---------------------------------------------------------------- 数据模型


@dataclass
class Violation:
    rule: str
    path: str
    line: int
    message: str
    detail: str = ""

    def key(self) -> str:
        return f"{self.rule}:{self.path}:{self.line}"

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass
class Report:
    violations: list[Violation] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)
    suppressions: list[dict] = field(default_factory=list)

    def add(self, rule: str, path: str, line: int, message: str, detail: str = "") -> None:
        self.violations.append(Violation(rule, path, line, message, detail))

    def count(self, rule: str) -> int:
        return sum(1 for item in self.violations if item.rule == rule)


# ---------------------------------------------------------------- 规则定义

RULES: dict[str, str] = {
    "ARCH001": "api 层不得横向 import 其它 api 模块（跨路由耦合）",
    "ARCH002": "services 不得 import api（依赖方向反转）",
    "ARCH003": "core 不得 import services/api（最内层被污染）",
    "ARCH004": "db 不得 import services/api（持久层被污染）",
    "ARCH005": "跨文件重复代码（精确副本）",
    "ARCH006": "结构性重复代码（改名/挪文件即可绕过的那类）",
    "ARCH007": "路由函数承担查询编排（应为薄适配器）",
    "ARCH008": "service 模块退化为单函数仓储包装（杂物层信号）",
    "ARCH009": "前后端契约字段漂移",
    "ARCH900": "基线被调大（棘轮失效）",
    "ARCH901": "抑制注释无理由或已过期",
}

# 路由函数里出现这些调用即视为"在路由里做查询编排"
QUERY_CALLS = {
    "select",
    "scalar",
    "scalars",
    "execute",
    "paginate",
    "count",
    "join",
    "outerjoin",
}

# 归一化时保留的语义属性（用于"精确副本"判定）
_SUPPRESSION = re.compile(r"#\s*arch:\s*ignore\b(?P<rest>.*)$")


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_py(root: Path):
    for path in sorted(root.rglob("*.py")):
        parts = set(path.parts)
        if parts & {".venv", "venv", "__pycache__", "node_modules", "alembic", ".git"}:
            continue
        # 排除门禁自身：检查器源码里必然出现规则名与示例字符串，
        # 扫自己只会产生噪声，且会让"自检通过"失去意义。
        if "tests" in parts and "architecture" in parts:
            continue
        # 排除自检夹具：自检会在仓库内生成临时夹具，若不排除，
        # 跑完自检再跑校验会把这些夹具当成真实代码，造成误报。
        # 注意只排除专用目录名，不能用泛化的 ".work"，
        # 否则会把别人正常的 .work 目录也跳过。
        if ".arch_selftest_work" in parts:
            continue
        yield path


def _module_name(root: Path, path: Path) -> str:
    rel = _rel(root, path)
    if rel.endswith(".py"):
        rel = rel[:-3]
    # 支持 root 为仓库根（backend/app/...）或后端根（app/...）两种用法
    if rel.startswith("backend/"):
        rel = rel[len("backend/") :]
    return rel.replace("/", ".")


def _layer(module: str) -> str | None:
    """从模块名推断所属层。只认 app.xxx 这一层，其余返回 None。"""
    parts = module.split(".")
    if len(parts) >= 2 and parts[0] == "app":
        return parts[1]
    return None


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return None


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return None


# ---------------------------------------------------------------- 规则实现


def check_imports(root: Path, report: Report) -> None:
    """ARCH001-004：import 方向。"""
    for path in _iter_py(root):
        module = _module_name(root, path)
        src_layer = _layer(module)
        if src_layer is None:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            targets: list[tuple[str, int]] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                targets.append((node.module, node.lineno))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    targets.append((alias.name, node.lineno))
            for target, lineno in targets:
                dst_layer = _layer(target)
                if dst_layer is None:
                    continue
                # ARCH001：api -> api，且不是自己的子模块
                if src_layer == "api" and dst_layer == "api":
                    # 只有"导入自己的子模块"才允许（如 app.api.v1.runs 导入
                    # app.api.v1.runs.foo）。同包内的兄弟模块属横向耦合。
                    is_own_submodule = target == module or target.startswith(module + ".")
                    if not is_own_submodule:
                        report.add(
                            "ARCH001",
                            _rel(root, path),
                            lineno,
                            f"api 模块 {module} 横向依赖 {target}",
                            "把共用逻辑下沉到 app/services，不要在路由之间互相 import",
                        )
                # ARCH002：services -> api
                elif src_layer == "services" and dst_layer == "api":
                    report.add(
                        "ARCH002",
                        _rel(root, path),
                        lineno,
                        f"services 模块 {module} 反向依赖 {target}",
                        "服务层不得感知 HTTP 层",
                    )
                # ARCH003：core -> services/api
                elif src_layer == "core" and dst_layer in {"services", "api"}:
                    report.add(
                        "ARCH003",
                        _rel(root, path),
                        lineno,
                        f"core 模块 {module} 依赖外层 {target}",
                        "core 是最内层，只能被依赖",
                    )
                # ARCH004：db -> services/api
                elif src_layer == "db" and dst_layer in {"services", "api"}:
                    report.add(
                        "ARCH004",
                        _rel(root, path),
                        lineno,
                        f"db 模块 {module} 依赖外层 {target}",
                        "持久层不得依赖业务层",
                    )


def _collect_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


class _Normalizer(ast.NodeTransformer):
    """把标识符归一化，抹掉改名带来的差异。

    keep_attrs=True  仅抹局部变量与参数名（保留 obj.attr 语义）→ 精确副本指纹
    keep_attrs=False 连属性和字符串常量一起抹掉 → 结构指纹
    """

    def __init__(self, keep_attrs: bool) -> None:
        self.keep_attrs = keep_attrs

    def visit_Name(self, node: ast.Name) -> ast.AST:
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        return ast.copy_location(ast.arg(arg="_", annotation=None), node)

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        if not self.keep_attrs:
            node.attr = "_"
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if not self.keep_attrs and isinstance(node.value, (str, int, float)):
            return ast.copy_location(ast.Constant(value="_"), node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._strip(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._strip(node)

    def _strip(self, node):
        node.name = "_"
        node.decorator_list = []
        # 去掉 docstring，避免注释差异影响判定
        body = [
            item
            for item in node.body
            if not (
                isinstance(item, ast.Expr)
                and isinstance(item.value, ast.Constant)
                and isinstance(item.value.value, str)
            )
        ]
        node.body = body or node.body
        self.generic_visit(node)
        return node


def _fingerprint(fn, keep_attrs: bool) -> tuple[str, int]:
    clone = copy.deepcopy(fn)
    normalized = _Normalizer(keep_attrs).visit(clone)
    ast.fix_missing_locations(normalized)
    dump = ast.dump(normalized, annotate_fields=False, include_attributes=False)
    # 统计全部语句（含嵌套），而非仅顶层，避免把真实函数误判为"太短"
    statements = sum(1 for node in ast.walk(normalized) if isinstance(node, ast.stmt))
    return dump, statements


def check_duplicates(root: Path, report: Report, min_statements: int = 4) -> None:
    """ARCH005/006：跨文件重复代码。

    关键：指纹是全仓唯一的。把重复函数挪到第三个文件不会降低计数。
    """
    exact: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    struct: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    exact_of_struct: dict[str, set[str]] = defaultdict(set)

    for path in _iter_py(root):
        tree = _parse(path)
        if tree is None:
            continue
        rel = _rel(root, path)
        for fn in _collect_functions(tree):
            fp_exact, stmts = _fingerprint(fn, keep_attrs=True)
            if stmts < min_statements:
                continue
            fp_struct, _ = _fingerprint(fn, keep_attrs=False)
            exact[fp_exact].append((rel, fn.lineno, fn.name))
            struct[fp_struct].append((rel, fn.lineno, fn.name))
            exact_of_struct[fp_struct].add(fp_exact)

    exact_groups: list[str] = []
    for fp, locations in exact.items():
        files = {item[0] for item in locations}
        if len(files) < 2:
            continue
        names = ", ".join(f"{p}:{ln}({n})" for p, ln, n in locations)
        first = locations[0]
        report.add(
            "ARCH005",
            first[0],
            first[1],
            f"精确重复代码 {len(locations)} 处：{names}",
            "合并为单一实现（通常下沉到 services）",
        )
        # 关键：重复计数用"涉及的函数总数"而非"组数"。
        # 否则把 2 处重复复制成 3 处时组数不变，棘轮会漏放。
        report.metrics["ARCH005"] = report.metrics.get("ARCH005", 0) + len(locations)
        exact_groups.append(fp)

    for fp, locations in struct.items():
        files = {item[0] for item in locations}
        if len(files) < 2:
            continue
        # 该结构组若已全部由精确副本解释，则不重复报 ARCH006
        if exact_of_struct.get(fp, set()) and all(
            group in exact_groups for group in exact_of_struct[fp]
        ):
            continue
        names = ", ".join(f"{p}:{ln}({n})" for p, ln, n in locations)
        first = locations[0]
        report.add(
            "ARCH006",
            first[0],
            first[1],
            f"结构性重复 {len(locations)} 处：{names}",
            "形状相同、仅实体名不同，通常是复制粘贴后改名的产物",
        )
        report.metrics["ARCH006"] = report.metrics.get("ARCH006", 0) + len(locations)


def check_fat_routes(root: Path, report: Report, threshold: int = 4) -> None:
    """ARCH007：路由函数里做查询编排。"""
    for path in _iter_py(root):
        rel = _rel(root, path)
        if "/api/" not in f"/{rel}" and not rel.startswith("app/api"):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for fn in _collect_functions(tree):
            is_route = False
            for deco in fn.decorator_list:
                target = deco.func if isinstance(deco, ast.Call) else deco
                if isinstance(target, ast.Attribute) and isinstance(
                    target.value, ast.Name
                ):
                    if target.value.id == "router":
                        is_route = True
            if not is_route:
                continue
            hits = 0
            for node in ast.walk(fn):
                name = _call_name(node)
                if name and name in QUERY_CALLS:
                    hits += 1
            if hits > threshold:
                report.add(
                    "ARCH007",
                    rel,
                    fn.lineno,
                    f"路由 {fn.name} 内出现 {hits} 次查询调用（阈值 {threshold}）",
                    "把查询编排移入 services，路由只做鉴权 + 调用 + 返回",
                )


def check_thin_services(root: Path, report: Report, max_lines: int = 40) -> None:
    """ARCH008：service 模块退化为单函数仓储包装。"""
    svc = root / "backend" / "app" / "services"
    if not svc.is_dir():
        svc = root / "app" / "services"
    if not svc.is_dir():
        return
    for path in sorted(svc.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = _parse(path)
        if tree is None:
            continue
        public = [
            fn
            for fn in tree.body
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not fn.name.startswith("_")
        ]
        lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        if len(public) <= 1 and lines <= max_lines:
            report.add(
                "ARCH008",
                _rel(root, path),
                public[0].lineno if public else 1,
                f"service 模块仅 {lines} 行、{len(public)} 个公开函数",
                "这类模块更像仓储辅助，考虑并入调用方或合并到同域 service",
            )


_IFACE = re.compile(r"export\s+interface\s+(?P<name>\w+)\s*\{(?P<body>[^}]*)\}", re.S)
_FIELD = re.compile(r"^\s*(?P<name>[A-Za-z_]\w*)\??\s*:", re.M)


def check_contract_drift(root: Path, report: Report) -> None:
    """ARCH009：前端 contracts.ts 手写镜像出现后端没有的字段。"""
    fe = None
    for candidate in (
        root / "frontend" / "src" / "services" / "api" / "contracts.ts",
        root / "frontend" / "src" / "types.ts",
    ):
        if candidate.is_file():
            fe = candidate
            break
    if fe is None:
        return

    backend_fields: set[str] = set()
    schemas = None
    for candidate in (root / "backend" / "app" / "schemas", root / "app" / "schemas"):
        if candidate.is_dir():
            schemas = candidate
            break
    if schemas is not None:
        for path in schemas.glob("*.py"):
            tree = _parse(path)
            if tree is None:
                continue
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                for stmt in node.body:
                    if isinstance(stmt, ast.AnnAssign) and isinstance(
                        stmt.target, ast.Name
                    ):
                        backend_fields.add(stmt.target.id)

    def to_camel(name: str) -> str:
        head, *rest = name.split("_")
        return head + "".join(part.capitalize() for part in rest)

    backend_camel = {to_camel(item) for item in backend_fields}
    text = fe.read_text(encoding="utf-8", errors="replace")
    for match in _IFACE.finditer(text):
        name = match.group("name")
        if not name.startswith("Backend"):
            continue
        line = text[: match.start()].count("\n") + 1
        for fmatch in _FIELD.finditer(match.group("body")):
            fname = fmatch.group("name")
            if fname in {"items", "total", "page", "pageSize"}:
                continue
            if fname not in backend_camel:
                report.add(
                    "ARCH009",
                    _rel(root, fe),
                    line,
                    f"前端契约 {name}.{fname} 在后端 schema 中找不到对应字段",
                    "手写镜像已漂移；优先改为由 OpenAPI 生成契约",
                )


def collect_suppressions(root: Path, report: Report) -> None:
    """ARCH901：抑制注释必须有理由与到期日。"""
    for path in _iter_py(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines, start=1):
            match = _SUPPRESSION.search(line)
            if not match:
                continue
            rest = match.group("rest").strip()
            entry = {"path": _rel(root, path), "line": index, "raw": rest}
            report.suppressions.append(entry)
            if "reason=" not in rest:
                report.add(
                    "ARCH901",
                    _rel(root, path),
                    index,
                    "抑制注释缺少 reason=",
                    "格式：# arch: ignore rule=ARCH00X reason=<为什么> until=YYYY-MM-DD",
                )
            elif "until=" not in rest:
                report.add(
                    "ARCH901",
                    _rel(root, path),
                    index,
                    "抑制注释缺少 until=",
                    "没有到期日的抑制等同于永久消音",
                )
            else:
                expiry = rest.split("until=", 1)[1].split()[0]
                if expiry < _TODAY:
                    report.add(
                        "ARCH901",
                        _rel(root, path),
                        index,
                        f"抑制已过期（until={expiry}）",
                        "到期后必须修复或重新评审，不能静默延期",
                    )


# ---------------------------------------------------------------- 主流程


def run_checks(root: Path) -> Report:
    report = Report()
    check_imports(root, report)
    check_duplicates(root, report)
    check_fat_routes(root, report)
    check_thin_services(root, report)
    check_contract_drift(root, report)
    collect_suppressions(root, report)

    # ARCH005/006 的计数在 check_duplicates 里按"涉及函数数"累加
    # （不是组数，否则复制成 3 份时组数不变会漏放）。其余规则按违规条数计。
    weighted = {"ARCH005", "ARCH006"}
    for rule in RULES:
        if rule not in weighted:
            report.metrics[rule] = report.count(rule)
    for rule in weighted:
        report.metrics.setdefault(rule, 0)
    report.metrics["suppressions"] = len(report.suppressions)
    return report


def load_baseline(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def compare_with_baseline(report: Report, baseline: dict) -> list[str]:
    """棘轮：实际数不得超过基线；基线也不得被调大。"""
    problems: list[str] = []
    base_counts = baseline.get("counts", {})
    for rule, base in base_counts.items():
        actual = report.metrics.get(rule, 0)
        if actual > base:
            problems.append(
                f"[{rule}] 违规数 {actual} > 基线 {base} —— 新增了违规。{RULES.get(rule, '')}"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="架构约束检查")
    parser.add_argument("--root", default=".", help="仓库根目录")
    parser.add_argument("--baseline", default="arch_baseline.json")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = root / baseline_path

    report = run_checks(root)

    if args.update_baseline:
        old = load_baseline(baseline_path)
        old_counts = old.get("counts", {})
        grew = {
            rule: (old_counts.get(rule, 0), value)
            for rule, value in report.metrics.items()
            if value > old_counts.get(rule, 0)
        }
        if grew:
            # 基线只允许下调。调大基线等于给违规开后门，
            # 会让"必须修好"退化成"改个数字就好"，因此直接拒绝。
            print("拒绝写入：以下规则基线被调大。基线只允许下调。")
            for rule, (before, after) in grew.items():
                print(f"  {rule}: {before} -> {after}")
            print("\n请先把这些违规真正修掉，再重新执行 --update-baseline。")
            return 1
        payload = {
            "version": 2,
            "note": "零容忍基线：任何架构违规都会导致 CI 失败。修复后无需改动此文件；禁止使用 --update-baseline 重新放宽。",
            "counts": report.metrics,
            "suppressions": report.suppressions,
        }
        baseline_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"baseline written -> {baseline_path}")
        return 0

    baseline = load_baseline(baseline_path)
    problems = compare_with_baseline(report, baseline)

    if args.json:
        print(
            json.dumps(
                {
                    "metrics": report.metrics,
                    "violations": [v.to_dict() for v in report.violations],
                    "problems": problems,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if problems else 0

    print("== 架构指标 ==")
    for rule, value in report.metrics.items():
        base = baseline.get("counts", {}).get(rule)
        marker = ""
        if base is not None:
            marker = f"  (基线 {base})" + ("" if value <= base else "  ↑ 超基线")
        print(f"  {rule:8s} {value:4d}{marker}")

    if report.violations:
        print("\n== 违规明细 ==")
        for item in report.violations:
            print(f"  {item.rule} {item.path}:{item.line}  {item.message}")

    if problems:
        print("\n== 棘轮校验失败 ==")
        for line in problems:
            print(f"  {line}")
        return 1

    print("\nOK: 未发现新增架构违规")
    return 0


if __name__ == "__main__":
    sys.exit(main())
