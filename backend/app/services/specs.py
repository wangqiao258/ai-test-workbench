"""项目规格文件：路径安全、YAML 解析、用例索引同步。"""

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.time import utcnow
from app.db.models.case import TestCase
from app.services.case_markers import replace_requirement_markers
from pytest_workbench.metadata import extract_marker_metadata

_ALLOWED_SUFFIXES = {".yaml", ".yml"}


@dataclass(frozen=True)
class ParsedCase:
    test_name: str
    requirements: tuple[str, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class SpecFileInfo:
    path: str
    size: int
    updated_at: datetime
    sha256: str
    case_count: int
    valid: bool
    error: str | None = None


def project_spec_root(project_id: UUID) -> Path:
    return (Path(get_settings().storage_dir) / "specs" / str(project_id)).resolve()


def spec_ref_prefix(project_id: UUID) -> str:
    storage = Path(get_settings().storage_dir).as_posix().strip("/")
    return f"{storage}/specs/{project_id}/"


def spec_file_ref(project_id: UUID, relative: Path) -> str:
    return f"{spec_ref_prefix(project_id)}{relative.as_posix()}"


def relative_spec_path(project_id: UUID, file_part: str) -> Path | None:
    prefix = spec_ref_prefix(project_id)
    if file_part.startswith(prefix):
        return Path(file_part[len(prefix) :])
    return None


def normalize_spec_path(raw: str) -> Path:
    value = raw.strip()
    if not value:
        raise ApiError(422, "invalid_spec_path", "spec 路径不能为空")
    if "\\" in value:
        raise ApiError(422, "invalid_spec_path", "spec 路径使用 / 分隔")
    path = Path(value)
    if value.startswith("/") or path.is_absolute() or path.drive or ".." in path.parts:
        raise ApiError(422, "invalid_spec_path", "spec 路径必须是相对路径且不能包含 ..")
    if path.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise ApiError(422, "invalid_spec_suffix", "只接受 .yaml / .yml 文件")
    return path


def resolve_spec_file(project_id: UUID, raw: str) -> tuple[Path, Path]:
    relative = normalize_spec_path(raw)
    root = project_spec_root(project_id)
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ApiError(422, "invalid_spec_path", "spec 路径超出允许目录")
    return relative, target


def parse_spec_content(content: str) -> list[ParsedCase]:
    try:
        documents = list(yaml.safe_load_all(content))
    except yaml.YAMLError as exc:
        raise ApiError(422, "invalid_spec_yaml", f"YAML 解析失败：{exc}") from exc

    cases: list[ParsedCase] = []
    seen: set[str] = set()
    for document in documents:
        items = document if isinstance(document, list) else [document]
        for item in items:
            if not isinstance(item, dict):
                continue
            test_name = item.get("test_name")
            if not isinstance(test_name, str) or not test_name.strip():
                continue
            name = test_name.strip()
            if name in seen:
                raise ApiError(
                    422,
                    "duplicate_test_name",
                    "同一文件内 test_name 不能重复",
                    details={"testName": name},
                )
            seen.add(name)
            marks = item.get("marks") or []
            if isinstance(marks, str):
                marks = [marks]
            requirements, tags = extract_marker_metadata(
                str(mark) for mark in marks if isinstance(mark, (str, int, float))
            )
            cases.append(
                ParsedCase(
                    test_name=name,
                    requirements=tuple(requirements),
                    tags=tuple(tags),
                )
            )
    return cases


def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def save_spec_content(
    project_id: UUID,
    raw_path: str,
    content: str,
    expected_sha256: str | None = None,
) -> tuple[Path, str, list[ParsedCase]]:
    relative, target = resolve_spec_file(project_id, raw_path)
    if expected_sha256 and target.exists():
        current = hashlib.sha256(target.read_bytes()).hexdigest()
        if current != expected_sha256:
            raise ApiError(
                409,
                "spec_conflict",
                "规格已被修改，请刷新后重试",
                details={"currentSha256": current},
            )
    parsed = parse_spec_content(content)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, target)
    return relative, content_sha256(content), parsed


def delete_spec_file(project_id: UUID, raw_path: str) -> tuple[Path, str]:
    relative, target = resolve_spec_file(project_id, raw_path)
    if not target.is_file():
        raise ApiError(404, "spec_not_found", "规格文件不存在")
    target.unlink()
    return relative, spec_file_ref(project_id, relative)


def read_spec_file(project_id: UUID, raw_path: str) -> tuple[Path, str, str, datetime]:
    relative, target = resolve_spec_file(project_id, raw_path)
    if not target.is_file():
        raise ApiError(404, "spec_not_found", "规格文件不存在")
    content = target.read_text(encoding="utf-8")
    updated_at = datetime.fromtimestamp(target.stat().st_mtime).astimezone()
    return relative, content, content_sha256(content), updated_at


def list_spec_files(project_id: UUID) -> list[SpecFileInfo]:
    root = project_spec_root(project_id)
    if not root.is_dir():
        return []
    files: list[SpecFileInfo] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _ALLOWED_SUFFIXES:
            continue
        relative = path.relative_to(root)
        content = path.read_text(encoding="utf-8", errors="replace")
        case_count = 0
        valid = True
        error: str | None = None
        try:
            case_count = len(parse_spec_content(content))
        except ApiError as exc:
            valid = False
            error = exc.message
        stat = path.stat()
        files.append(
            SpecFileInfo(
                path=relative.as_posix(),
                size=stat.st_size,
                updated_at=datetime.fromtimestamp(stat.st_mtime).astimezone(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                case_count=case_count,
                valid=valid,
                error=error,
            )
        )
    return files


def sync_spec_cases(
    db: Session, project_id: UUID, relative: Path, parsed: list[ParsedCase]
) -> tuple[int, int]:
    """按文件内容同步用例索引；被移除的用例归档，不物理删除。"""
    file_ref = spec_file_ref(project_id, relative)
    now = utcnow()
    existing = {
        case.nodeid: case
        for case in db.scalars(
            select(TestCase).where(
                TestCase.project_id == project_id, TestCase.file == file_ref
            )
        )
    }
    wanted: set[str] = set()
    for item in parsed:
        nodeid = f"{file_ref}::{item.test_name}"
        wanted.add(nodeid)
        test_case = existing.get(nodeid) or db.scalar(
            select(TestCase).where(
                TestCase.project_id == project_id, TestCase.nodeid == nodeid
            )
        )
        if test_case is None:
            test_case = TestCase(project_id=project_id, nodeid=nodeid, first_seen_at=now)
            db.add(test_case)
        test_case.file = file_ref
        test_case.name = item.test_name
        test_case.tags = list(item.tags)
        test_case.last_seen_at = now
        db.flush()
        replace_requirement_markers(
            db, project_id, test_case.id, list(item.requirements)
        )

    archived = 0
    for nodeid, test_case in existing.items():
        if nodeid not in wanted and test_case.archived_at is None:
            test_case.archived_at = now
            archived += 1
    db.flush()
    return len(wanted), archived


def archive_spec_cases(db: Session, project_id: UUID, file_ref: str) -> int:
    cases = list(
        db.scalars(
            select(TestCase).where(
                TestCase.project_id == project_id,
                TestCase.file == file_ref,
                TestCase.archived_at.is_(None),
            )
        )
    )
    now = utcnow()
    for test_case in cases:
        test_case.archived_at = now
    db.flush()
    return len(cases)
