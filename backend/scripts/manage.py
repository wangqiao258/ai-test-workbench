import argparse
import getpass
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import ISSUABLE_TOKEN_SCOPES
from app.core.secrets import encrypt_secret
from app.core.security import generate_api_token, hash_password
from app.db.models.identity import AppUser, ProjectMember
from app.db.models.project import ApiToken, Project
from app.db.session import SessionLocal
from app.schemas.project import ProjectEntry

ROLES = ("viewer", "tester", "reviewer", "admin")

# 待下线端点：只做标记与统计，不改变业务行为。
DEPRECATED_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/projects/{project_id}/summary"): "前端未调用，待真实访问数据确认",
    ("GET", "/projects/{project_id}/audit"): "前端未调用，待确认是否保留全局审计查询",
    ("GET", "/projects/{project_id}/runs/{run_ref}"): "前端未调用，列表接口已包含同等字段",
    (
        "GET",
        "/projects/{project_id}/findings/{finding_id}",
    ): "前端未调用，列表与 ingest bundle 已覆盖",
}


def _fail(message: str) -> None:
    print(f"错误：{message}", file=sys.stderr)
    raise SystemExit(1)


def _resolve_project(db, ref: str) -> Project | None:
    """按项目 ID 或名称定位项目；名称重复时要求改用 ID。"""
    try:
        project = db.get(Project, UUID(ref))
    except ValueError:
        project = None
    if project is not None:
        return project
    matches = db.scalars(select(Project).where(Project.name == ref)).all()
    if len(matches) > 1:
        _fail(f"项目名称 {ref} 不唯一，请改用项目 id")
    return matches[0] if matches else None


def cmd_create_user(args: argparse.Namespace) -> None:
    password = args.password or getpass.getpass("密码：")
    if len(password) < 8:
        _fail("密码至少 8 位")
    email = args.email.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(AppUser).where(AppUser.email == email)) is not None:
            _fail(f"用户 {email} 已存在")
        user = AppUser(email=email, display_name=args.name, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        print(f"已创建用户 {user.email}，id={user.id}")


def _parse_entries(raw_entries: list[str]) -> list[dict]:
    entries: list[dict] = []
    seen_urls: set[str] = set()
    for raw in raw_entries:
        name, separator, url = raw.partition("=")
        if not separator:
            _fail(f"入口格式应为 NAME=URL：{raw}")
        try:
            entry = ProjectEntry(name=name, url=url)
        except ValueError as exc:
            _fail(f"入口不合法：{raw}（{exc}）")
        if entry.url in seen_urls:
            _fail(f"入口地址重复：{entry.url}")
        seen_urls.add(entry.url)
        entries.append(entry.model_dump())
    return entries


def cmd_create_project(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        project = Project(name=args.name, entries=_parse_entries(args.entry))
        db.add(project)
        db.commit()
        print(f"已创建项目 {project.name}，id={project.id}")


def cmd_add_member(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        project = _resolve_project(db, args.project)
        if project is None:
            _fail(f"项目 {args.project} 不存在")
        email = args.email.strip().lower()
        user = db.scalar(select(AppUser).where(AppUser.email == email))
        if user is None:
            _fail(f"用户 {email} 不存在")
        member = db.get(ProjectMember, (project.id, user.id))
        if member is None:
            member = ProjectMember(project_id=project.id, user_id=user.id, role=args.role)
            db.add(member)
        else:
            member.role = args.role
        db.commit()
        print(f"已将 {email} 加入 {project.name}，角色 {args.role}")


def cmd_create_token(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        project = _resolve_project(db, args.project)
        if project is None:
            _fail(f"项目 {args.project} 不存在")
        raw, prefix, digest = generate_api_token()
        expires_at = None
        if args.expires_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=args.expires_days)
        token = ApiToken(
            project_id=project.id,
            name=args.name,
            token_prefix=prefix,
            token_hash=digest,
            token_ciphertext=encrypt_secret(raw),
            scopes=args.scope or list(ISSUABLE_TOKEN_SCOPES),
            expires_at=expires_at,
        )
        db.add(token)
        db.commit()
        print(f"项目 {project.name} 的 Token 已创建，可在项目设置查看：")
        print(raw)
        if expires_at is not None:
            print(f"过期时间：{expires_at.isoformat()}")


def _iter_access_records(paths: list[Path]):
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def cmd_usage_report(args: argparse.Namespace) -> None:
    log_path = Path(get_settings().access_log_path).expanduser()
    files = sorted(log_path.parent.glob(log_path.name + "*"))
    if not files:
        _fail(f"访问日志不存在：{log_path}")

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    counts: Counter[tuple[str, str]] = Counter()
    last_seen: dict[tuple[str, str], str] = {}
    route_totals: Counter[str] = Counter()
    total = 0
    for record in _iter_access_records(files):
        if not args.include_testclient and record.get("client") == "testclient":
            continue
        raw_ts = str(record.get("ts") or "")
        try:
            when = datetime.fromisoformat(raw_ts)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when < since:
            continue
        total += 1
        key = (str(record.get("method") or ""), str(record.get("route") or ""))
        counts[key] += 1
        last_seen[key] = max(last_seen.get(key, ""), raw_ts)
        route_totals[key[1]] += 1

    scope_note = "（含 testclient）" if args.include_testclient else "（已排除 testclient）"
    print(f"统计窗口：最近 {args.days} 天{scope_note}")
    print(f"总请求：{total}")
    print("\n待下线端点：")
    for (method, route), reason in DEPRECATED_ROUTES.items():
        hits = counts.get((method, route), 0)
        last = last_seen.get((method, route), "-")
        print(f"  {method:6s} {route:55s} {hits:5d} 次  最近 {last}  {reason}")
    if args.top:
        print(f"\n访问量 Top {args.top}：")
        for route, hits in route_totals.most_common(args.top):
            print(f"  {hits:5d}  {route}")
    if total == 0:
        print("\n没有可用的真实访问记录。部署后收集 2–4 周再重跑本报告。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manage", description="AI 协同测试工作台后端管理命令")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user", help="创建登录用户")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--password", help="不填则交互输入")
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("create-project", help="创建项目")
    p.add_argument("--name", required=True)
    p.add_argument(
        "--entry",
        action="append",
        default=[],
        metavar="NAME=URL",
        help="测试入口，可重复，如 --entry 小程序=https://m.example.com",
    )
    p.set_defaults(func=cmd_create_project)

    p = sub.add_parser("add-member", help="把用户加入项目")
    p.add_argument("--project", required=True, help="项目 id 或名称")
    p.add_argument("--email", required=True)
    p.add_argument("--role", choices=ROLES, default="viewer")
    p.set_defaults(func=cmd_add_member)

    p = sub.add_parser("create-token", help="为项目创建接入 Token")
    p.add_argument("--project", required=True, help="项目 id 或名称")
    p.add_argument("--name", required=True, help="Token 用途，如 local-pytest")
    p.add_argument("--expires-days", type=int, default=None)
    p.add_argument(
        "--scope",
        action="append",
        choices=ISSUABLE_TOKEN_SCOPES,
        default=None,
        help="可重复指定；默认全部细分权限。写权限自动包含对应读权限",
    )
    p.set_defaults(func=cmd_create_token)

    p = sub.add_parser("usage-report", help="统计访问日志，评估待下线端点的真实使用量")
    p.add_argument("--days", type=int, default=30, help="统计最近多少天，默认 30")
    p.add_argument("--top", type=int, default=10, help="额外输出访问量前 N 的路由，0 表示不输出")
    p.add_argument(
        "--include-testclient",
        action="store_true",
        help="包含自动化测试流量（默认排除 client=testclient）",
    )
    p.set_defaults(func=cmd_usage_report)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
