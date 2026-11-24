from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.project import Project
from app.db.models.run_request import RunRequest
from app.db.session import SessionLocal
from workbench_runner.config import RunnerSettings

logger = logging.getLogger("workbench_runner.worker")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _claim_request(db: Session) -> uuid.UUID | None:
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
    now = _utcnow()
    request.status = "running"
    request.started_at = now
    request.run_external_id = f"RUN-REQ-{now:%Y%m%d-%H%M%S}-{request_id.hex[:6]}"
    db.commit()
    return request_id


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
    request.finished_at = _utcnow()
    db.commit()


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

        token = settings.project_tokens.get(project.key)
        if not token:
            _finish(db, request, "failed", error=f"项目 {project.key} 未配置 Runner Token")
            return

        try:
            specs = _resolve_specs(request.spec_paths or [], settings.spec_dir)
        except ValueError as exc:
            _finish(db, request, "failed", error=str(exc))
            return

        captured_dir = run_dir / "captured_traffic"
        command = [
            sys.executable,
            "-m",
            "pytest",
            *specs,
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

        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"$ {' '.join(command)}\n\n")
            log.flush()
            try:
                completed = subprocess.run(
                    command,
                    cwd=settings.spec_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=settings.run_timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                log.write(f"\n[runner] 执行超时（{settings.run_timeout_seconds}s）\n")
                _finish(db, request, "failed", error="执行超时")
                return
            except OSError as exc:
                log.write(f"\n[runner] 启动 pytest 失败：{exc}\n")
                _finish(db, request, "failed", error=f"启动 pytest 失败：{exc}")
                return

            log.write(completed.stdout or "")
            log.write(completed.stderr or "")

        passed = completed.returncode in (0, 1)
        output = (completed.stderr or completed.stdout or "").strip()
        _finish(
            db,
            request,
            "succeeded" if passed else "failed",
            exit_code=completed.returncode,
            error=None if passed else output[-4000:],
        )


def run_forever(settings: RunnerSettings, *, once: bool = False) -> None:
    settings.workdir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "runner started: platform=%s spec_dir=%s workdir=%s",
        settings.platform_url,
        settings.spec_dir,
        settings.workdir,
    )
    while True:
        try:
            with SessionLocal() as db:
                request_id = _claim_request(db)
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
        time.sleep(settings.poll_seconds)
