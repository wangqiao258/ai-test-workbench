import argparse
import getpass
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.core.deps import ISSUABLE_TOKEN_SCOPES
from app.core.secrets import encrypt_secret
from app.core.security import generate_api_token, hash_password
from app.db.models.identity import AppUser, ProjectMember
from app.db.models.project import ApiToken, Project
from app.db.session import SessionLocal

ROLES = ("viewer", "tester", "reviewer", "admin")


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


def cmd_create_project(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        project = Project(name=args.name, base_url=args.base_url.strip().rstrip("/"))
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
    p.add_argument("--base-url", default="", help="被测服务地址，如 http://127.0.0.1:8080")
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

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
