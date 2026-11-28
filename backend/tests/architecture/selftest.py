"""零依赖自检：不装 pytest 也能验证检查器本身是否正确。

CI 里跑它，保证"检查器自己没坏"。检查器失效比没有检查器更危险。
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
import traceback
from pathlib import Path

# 不依赖 tests/ 成为 Python 包：直接把检查器所在目录加入 sys.path。
# 这样接入时无需新增 tests/__init__.py，不会改变仓库原有 pytest 收集行为。
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import arch_rules as rules  # noqa: E402

FAILED: list[str] = []
PASSED: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
        PASSED.append(name)
    except AssertionError as exc:
        FAILED.append(f"{name}: {exc}")
    except Exception:
        FAILED.append(f"{name}: 异常\n{traceback.format_exc()}")


def write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    # 逐级创建：某些沙箱对递归 mkdir(parents=True) 会拒绝
    current = root
    for part in path.parent.relative_to(root).parts:
        current = current / part
        if not current.is_dir():
            current.mkdir()
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return path


LOADER = '''
    def _load_finding(db, project_id, finding_id):
        finding = db.scalar(select(Finding).where(Finding.project_id == project_id))
        if finding is None:
            raise ApiError(404, "finding_not_found", "AI finding 不存在")
        return finding
'''


def make_repo(root: Path) -> Path:
    write(root, "backend/app/api/v1/runs.py", "def run_out(run):\n    return {'id': run.id}\n")
    write(
        root,
        "backend/app/api/v1/projects.py",
        """
        from app.api.v1.runs import run_out

        def summary():
            return run_out(None)
        """,
    )
    write(
        root,
        "backend/app/services/bad_service.py",
        """
        from app.api.v1.projects import summary

        def do_work():
            return summary()
        """,
    )
    write(root, "backend/app/api/v1/findings.py", LOADER)
    write(root, "backend/app/api/ingest/review_read.py", LOADER)
    write(
        root,
        "backend/app/api/v1/cases.py",
        """
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("")
        def list_cases(db):
            conditions = []
            cases = db.scalars(select(TestCase).where(*conditions))
            rows = db.execute(select(Marker))
            total = db.scalar(select(func.count(TestCase.id)))
            page = db.scalars(select(TestCase).limit(10))
            return {"c": cases, "r": rows, "t": total, "p": page}
        """,
    )
    write(
        root,
        "backend/app/services/projects.py",
        '''
        def get_project_or_404(db, project_id):
            project = db.get(Project, project_id)
            if project is None:
                raise ApiError(404, "project_not_found", "项目不存在")
            return project
        ''',
    )
    return root


_CASE_SEQ = [0]


def _fresh() -> Path:
    # 夹具必须放在两个地方之外：
    #   1. tests/architecture —— 检查器跳过自身目录
    #   2. .arch_selftest_work —— 检查器跳过自检残留目录
    # 因此用独立的临时目录，且每次自检结束由 _cleanup 删除。
    base = Path(tempfile.gettempdir()) / "arch_gate_selftest"
    base.mkdir(parents=True, exist_ok=True)
    while True:
        _CASE_SEQ[0] += 1
        candidate = base / f"case{_CASE_SEQ[0]:03d}"
        if not candidate.exists():
            candidate.mkdir()
            return make_repo(candidate)


# ---------------------------------------------------------------- 能抓

def t_arch001() -> None:
    report = rules.run_checks(_fresh())
    hits = [v for v in report.violations if v.rule == "ARCH001"]
    assert hits, "未检测到 api 横向 import"
    assert any("app.api.v1.runs" in v.message for v in hits), hits[0].message


def t_arch002() -> None:
    report = rules.run_checks(_fresh())
    assert [v for v in report.violations if v.rule == "ARCH002"], "未检测到反向依赖"


def t_arch005() -> None:
    report = rules.run_checks(_fresh())
    hits = [v for v in report.violations if v.rule == "ARCH005"]
    assert hits, "未检测到跨文件精确副本"
    assert "_load_finding" in hits[0].message, hits[0].message


def t_arch007() -> None:
    report = rules.run_checks(_fresh())
    hits = [v for v in report.violations if v.rule == "ARCH007"]
    assert hits, "未检测到路由内查询编排"
    assert "list_cases" in hits[0].message


def t_arch008() -> None:
    report = rules.run_checks(_fresh())
    assert [v for v in report.violations if v.rule == "ARCH008"], "未检测到薄 service"


# ---------------------------------------------------------------- 假修复拦不住

def t_rename_function() -> None:
    root = _fresh()
    before = len([v for v in rules.run_checks(root).violations if v.rule in {"ARCH005", "ARCH006"}])
    write(
        root,
        "backend/app/api/v1/findings.py",
        '''
        def _fetch_finding_or_404(db, project_id, finding_id):
            finding = db.scalar(select(Finding).where(Finding.project_id == project_id))
            if finding is None:
                raise ApiError(404, "finding_not_found", "AI finding 不存在")
            return finding
        ''',
    )
    after = len([v for v in rules.run_checks(root).violations if v.rule in {"ARCH005", "ARCH006"}])
    assert after >= before, f"改名后计数从 {before} 降到 {after}，可被绕过"


def t_rename_locals() -> None:
    root = _fresh()
    before = len([v for v in rules.run_checks(root).violations if v.rule == "ARCH005"])
    write(
        root,
        "backend/app/api/v1/findings.py",
        '''
        def _load_finding(db, project_id, finding_id):
            row = db.scalar(select(Finding).where(Finding.project_id == project_id))
            if row is None:
                raise ApiError(404, "finding_not_found", "AI finding 不存在")
            return row
        ''',
    )
    after = len([v for v in rules.run_checks(root).violations if v.rule == "ARCH005"])
    assert after >= before, f"改局部变量后计数从 {before} 降到 {after}，可被绕过"


def _dup_footprint(root: Path) -> tuple[int, int]:
    """返回 (重复组数, 参与重复的函数总数)。

    假修复的特征：组数不变但函数总数上升（多复制了一份）；
    真修复的特征：组数下降。
    """
    import re as _re

    report = rules.run_checks(root)
    groups = 0
    members = 0
    for violation in report.violations:
        if violation.rule not in {"ARCH005", "ARCH006"}:
            continue
        groups += 1
        found = _re.search(r"(\d+)\s*处", violation.message)
        if found:
            members += int(found.group(1))
    return groups, members


def t_move_to_third_file() -> None:
    root = _fresh()
    groups_before, members_before = _dup_footprint(root)
    write(root, "backend/app/api/v1/findings.py", LOADER)
    write(root, "backend/app/api/ingest/review_read.py", LOADER)
    write(root, "backend/app/api/v1/helpers.py", LOADER)
    groups_after, members_after = _dup_footprint(root)
    assert members_after > members_before, (
        f"挪到第三个文件后参与重复的函数数应增加：{members_before} -> {members_after}"
    )


def t_real_merge() -> None:
    root = _fresh()
    groups_before, members_before = _dup_footprint(root)
    write(
        root,
        "backend/app/services/review.py",
        LOADER,
    )
    write(root, "backend/app/api/v1/findings.py", "from app.services.review import _load_finding\n")
    write(root, "backend/app/api/ingest/review_read.py", "from app.services.review import _load_finding\n")
    groups_after, members_after = _dup_footprint(root)
    assert members_after < members_before, (
        f"真正合并后参与重复的函数数必须下降：{members_before} -> {members_after}"
    )


# ---------------------------------------------------------------- 抑制注释

def t_suppression_needs_reason() -> None:
    root = _fresh()
    write(root, "backend/app/api/v1/legacy.py", "def thing():  # arch: ignore rule=ARCH001\n    return 1\n")
    report = rules.run_checks(root)
    assert [v for v in report.violations if v.rule == "ARCH901"], "无理由抑制未被拒绝"


def t_valid_suppression() -> None:
    root = _fresh()
    write(
        root,
        "backend/app/api/v1/legacy.py",
        "def thing():  # arch: ignore rule=ARCH001 reason=历史遗留 until=2027-01-01\n    return 1\n",
    )
    report = rules.run_checks(root)
    assert not [v for v in report.violations if v.rule == "ARCH901"], "合规抑制被误报"


# ---------------------------------------------------------------- 棘轮

def t_ratchet_blocks_increase() -> None:
    root = _fresh()
    report = rules.run_checks(root)
    base = {"counts": {rule: 0 for rule in rules.RULES}}
    problems = rules.compare_with_baseline(report, base)
    assert problems, "基线为 0 时应拦截一切违规"


def t_ratchet_blocks_third_copy() -> None:
    """棘轮必须拦住"复制成 3 份"：组数不变，但涉及函数数增加。

    这是最容易漏掉的假修复 —— 用组数计数会放过它。
    """
    root = _fresh()
    report = rules.run_checks(root)
    base_counts = dict(report.metrics)

    write(root, "backend/app/api/v1/helpers.py", LOADER)
    report2 = rules.run_checks(root)
    problems = rules.compare_with_baseline(report2, {"counts": base_counts})
    assert problems, (
        f"复制成 3 份未被拦截：ARCH005 {base_counts.get('ARCH005')} -> "
        f"{report2.metrics.get('ARCH005')}"
    )
    assert report2.metrics["ARCH005"] > base_counts["ARCH005"], "计数应按函数数增长"


def t_ratchet_allows_at_baseline() -> None:
    root = _fresh()
    report = rules.run_checks(root)
    base = {"counts": dict(report.metrics)}
    problems = rules.compare_with_baseline(report, base)
    assert not problems, f"等于基线时不应失败：{problems}"


def main() -> int:
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("t_") and callable(fn)
    ]
    for name, fn in tests:
        check(name, fn)

    # 自检夹具用完即删，避免污染仓库（CI 上也无残留）
    _cleanup()

    print(f"通过 {len(PASSED)} / {len(tests)}")
    if FAILED:
        print("\n失败：")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    print("OK: 检查器自检全部通过")
    return 0


def _cleanup() -> None:
    import shutil

    for base in (
        Path(tempfile.gettempdir()) / "arch_gate_selftest",
        Path(__file__).resolve().parents[2] / ".arch_selftest_work",
    ):
        if base.is_dir():
            shutil.rmtree(base, ignore_errors=True)

if __name__ == "__main__":
    sys.exit(main())
