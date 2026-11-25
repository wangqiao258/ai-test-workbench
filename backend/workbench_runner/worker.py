from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models.case import TestCase
from app.db.models.project import Project
from app.db.models.run_request import RunRequest
from app.db.session import SessionLocal
from app.services.specs import relative_spec_path, spec_file_ref
from workbench_runner.config import RunnerSettings

logger = logging.getLogger("workbench_runner.worker")

_stop = threading.Event()


def _request_stop(signum: int, _frame: object) -> None:
    logger.info("收到信号 %s，结束当前任务后退出", signum)
    _stop.set()


def _lease_until(settings: RunnerSettings, now: datetime) -> datetime:
    return now + timedelta(seconds=settings.lease_seconds)


def _claim_request(db: Session, settings: RunnerSettings) -> uuid.UUID | None:
    request = db.execute(
        select(RunRequest)
        .where(RunRequest.status == "queued")
        .order_by(RunRequest.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()
    if request is None:
        return None
    request_id = request.id
    now = utcnow()
    request.status = "running"
    request.started_at = now
    request.attempt += 1
    request.heartbeat_at = now
    request.lease_expires_at = _lease_until(settings, now)
    request.run_external_id = (
        f"RUN-REQ-{now.astimezone():%Y%m%d-%H%M%S}-{request_id.hex[:6]}"
    )
    request.exit_code = None
    request.error = None
    request.finished_at = None
    db.commit()
    return request_id


def _release(request: RunRequest, max_attempts: int, reason: str) -> None:
    """释放租约：未超过重试上限则重新排队，否则标记失败。"""
    request.heartbeat_at = None
    request.lease_expires_at = None
    request.started_at = None
    request.finished_at = None
    request.run_external_id = None
    if request.attempt < max_attempts:
        request.status = "queued"
        request.error = reason
        return
    request.status = "failed"
    request.error = f"{reason}（已执行 {request.attempt} 次）"
    request.finished_at = utcnow()


def recover_stale(db: Session, settings: RunnerSettings) -> int:
    """回收租约过期的 running 任务，供启动时与轮询时调用。"""
    now = utcnow()
    stale = list(
        db.scalars(
            select(RunRequest)
            .where(
                RunRequest.status == "running",
                or_(
                    RunRequest.lease_expires_at.is_(None),
                    RunRequest.lease_expires_at < now,
                ),
            )
            .with_for_update(skip_locked=True)
        )
    )
    for request in stale:
        _release(request, settings.max_attempts, "执行器失联或重启，任务已回收")
    if stale:
        db.commit()
        logger.warning("回收失联运行任务 %s 个", len(stale))
    return len(stale)


def _heartbeat(db: Session, request_id: uuid.UUID, settings: RunnerSettings) -> None:
    request = db.get(RunRequest, request_id)
    if request is None or request.status != "running":
        return
    now = utcnow()
    request.heartbeat_at = now
    request.lease_expires_at = _lease_until(settings, now)
    db.commit()


def _finish(
    db: Session,
    request: RunRequest,
    status: str,
    *,
    exit_code: int | None = None,
    error: str | None = None,
) -> None:
    request.status = status
    request.exit_code = exit_code
    request.error = error
    request.finished_at = utcnow()
    request.heartbeat_at = None
    request.lease_expires_at = None
    db.commit()


def _terminate(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _resolve_specs(raw_paths: list[str], spec_dir: Path) -> list[str]:
    if not raw_paths:
        return [str(spec_dir)]
    specs: list[str] = []
    for raw in raw_paths:
        path = Path(raw)
        if not path.is_absolute():
            path = spec_dir / path
        path = path.resolve()
        if not path.is_relative_to(spec_dir):
            raise ValueError(f"spec path 超出允许目录：{raw}")
        specs.append(str(path))
    return specs


def _case_target(nodeid: str, project_id: uuid.UUID, spec_dir: Path) -> Path:
    file_part, _, test_name = nodeid.partition("::")
    if not test_name:
        raise ValueError(f"无效的用例 nodeid：{nodeid}")
    relative = relative_spec_path(project_id, file_part)
    if relative is not None:
        target = (spec_dir / relative).resolve()
    else:
        path = Path(file_part)
        target = (path if path.is_absolute() else spec_dir / path).resolve()
    if not target.is_relative_to(spec_dir):
        raise ValueError(f"用例路径超出允许目录：{nodeid}")
    if not target.is_file():
        raise ValueError(f"用例文件不存在：{file_part}")
    return target


def _test_name(nodeid: str) -> str:
    return nodeid.split("::", 1)[1]


def _selection_args(
    case_nodeids: list[str], project_id: uuid.UUID, spec_dir: Path
) -> list[str]:
    return [
        f"{_case_target(nodeid, project_id, spec_dir)}::{_test_name(nodeid)}"
        for nodeid in case_nodeids
    ]


def _expand_targets(
    targets: list[str],
    archived: set[str],
    project_id: uuid.UUID,
    spec_dir: Path,
    db: Session,
) -> list[str]:
    """有归档用例时把目录展开到文件，含归档的文件只执行其活动 nodeid。"""
    files: list[Path] = []
    for raw in targets:
        path = Path(raw)
        if path.is_dir():
            files.extend(
                sorted(
                    item
                    for item in path.rglob("*")
                    if item.is_file() and item.suffix.lower() in {".yaml", ".yml"}
                )
            )
        else:
            files.append(path)

    args: list[str] = []
    for file_path in files:
        relative = file_path.resolve().relative_to(spec_dir)
        file_ref = spec_file_ref(project_id, relative)
        prefix = f"{file_ref}::"
        if not any(nodeid.startswith(prefix) for nodeid in archived):
            args.append(str(file_path))
            continue
        active = list(
            db.scalars(
                select(TestCase.nodeid).where(
                    TestCase.project_id == project_id,
                    TestCase.file == file_ref,
                    TestCase.archived_at.is_(None),
                )
            )
        )
        args.extend(_selection_args(active, project_id, spec_dir))
    if not args:
        raise ValueError("没有可执行的用例：选中的用例均已归档")
    return args


def _log_tail(log_path: Path, limit: int = 4000) -> str:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-40:])[-limit:]


def execute_request(request_id: uuid.UUID, settings: RunnerSettings) -> None:
    with SessionLocal() as db:
        request = db.get(RunRequest, request_id)
        if request is None or request.status != "running":
            return

        project = db.get(Project, request.project_id)
        run_dir = settings.workdir / "runs" / str(request_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "runner.log"
        request.log_path = str(log_path)
        db.commit()

        if project is None:
            _finish(db, request, "failed", error="项目不存在")
            return

        token = settings.project_tokens.get(str(project.id))
        if not token:
            _finish(
                db,
                request,
                "failed",
                error=f"项目 {project.name}（{project.id}）未配置 Runner Token",
            )
            return

        project_spec_dir = (settings.spec_dir / str(project.id)).resolve()
        if not project_spec_dir.is_dir():
            _finish(db, request, "failed", error=f"项目 specs 目录不存在：{project_spec_dir}")
            return

        archived = set(
            db.scalars(
                select(TestCase.nodeid).where(
                    TestCase.project_id == project.id,
                    TestCase.archived_at.isnot(None),
                )
            )
        )
        case_nodeids = request.case_nodeids or []
        try:
            if case_nodeids:
                active_nodeids = [
                    nodeid for nodeid in case_nodeids if nodeid not in archived
                ]
                if not active_nodeids:
                    raise ValueError("选中的用例均已归档")
                targets = _selection_args(active_nodeids, project.id, project_spec_dir)
            else:
                targets = _resolve_specs(request.spec_paths or [], project_spec_dir)
                if archived:
                    targets = _expand_targets(
                        targets, archived, project.id, project_spec_dir, db
                    )
        except ValueError as exc:
            _finish(db, request, "failed", error=str(exc))
            return

        captured_dir = run_dir / "captured_traffic"
        command = [
            sys.executable,
            "-m",
            "pytest",
            *targets,
            "-q",
            "--capture-traffic",
            "--capture-dir",
            str(captured_dir),
            "--workbench-upload",
            "--workbench-url",
            settings.platform_url,
            "--workbench-har-dir",
            str(captured_dir),
            "--workbench-run-id",
            request.run_external_id or "",
        ]
        env = {
            **os.environ,
            "WORKBENCH_TOKEN": token,
            "PYTHONIOENCODING": "utf-8",
        }
        logger.info("run %s: %s", request.run_external_id, " ".join(command))

        timed_out = False
        interrupted = False
        completed_code: int | None = None
        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"$ {' '.join(command)}\n\n")
            log.flush()
            try:
                proc = subprocess.Popen(
                    command,
                    cwd=project_spec_dir,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as exc:
                log.write(f"\n[runner] 启动 pytest 失败：{exc}\n")
                _finish(db, request, "failed", error=f"启动 pytest 失败：{exc}")
                return

            deadline = time.monotonic() + settings.run_timeout_seconds
            last_beat = time.monotonic()
            while True:
                completed_code = proc.poll()
                if completed_code is not None:
                    break
                if _stop.is_set():
                    interrupted = True
                    log.write("\n[runner] 收到退出信号，终止当前运行并释放租约\n")
                    _terminate(proc)
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    log.write(f"\n[runner] 执行超时（{settings.run_timeout_seconds}s）\n")
                    _terminate(proc)
                    break
                if time.monotonic() - last_beat >= settings.heartbeat_seconds:
                    _heartbeat(db, request_id, settings)
                    last_beat = time.monotonic()
                time.sleep(1)
            proc.wait()
            log.flush()

        if interrupted:
            _release(request, settings.max_attempts, "执行器重启中断")
            db.commit()
            return

        if timed_out:
            _finish(db, request, "failed", error="执行超时")
            return

        passed = completed_code in (0, 1)
        _finish(
            db,
            request,
            "succeeded" if passed else "failed",
            exit_code=completed_code,
            error=None if passed else _log_tail(log_path),
        )


def run_forever(settings: RunnerSettings, *, once: bool = False) -> None:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    settings.workdir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "runner started: platform=%s spec_dir=%s workdir=%s",
        settings.platform_url,
        settings.spec_dir,
        settings.workdir,
    )
    while not _stop.is_set():
        try:
            with SessionLocal() as db:
                recover_stale(db, settings)
                request_id = _claim_request(db, settings)
            if request_id is not None:
                logger.info("claimed run request %s", request_id)
                execute_request(request_id, settings)
                if once:
                    return
            elif once:
                logger.info("no queued run request")
                return
        except Exception:
            logger.exception("runner loop failed")
            if once:
                raise
        if _stop.is_set():
            break
        time.sleep(settings.poll_seconds)
    logger.info("runner stopped")
