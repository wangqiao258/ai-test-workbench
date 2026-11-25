from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass(frozen=True)
class RunnerSettings:
    platform_url: str
    poll_seconds: float
    run_timeout_seconds: float
    heartbeat_seconds: float
    lease_seconds: float
    max_attempts: int
    workdir: Path
    spec_dir: Path
    project_tokens: dict[str, str]


def _load_project_tokens() -> dict[str, str]:
    raw = os.environ.get("WORKBENCH_PROJECT_TOKENS", "").strip()
    if raw:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("WORKBENCH_PROJECT_TOKENS 必须是 projectId -> token 的 JSON 对象")
        return {
            str(key): str(value)
            for key, value in data.items()
            if str(key).strip() and str(value).strip()
        }
    token = os.environ.get("WORKBENCH_PROJECT_TOKEN", "").strip()
    project_id = os.environ.get("WORKBENCH_PROJECT_ID", "").strip()
    return {project_id: token} if project_id and token else {}


def load_settings() -> RunnerSettings:
    return RunnerSettings(
        platform_url=os.environ.get(
            "WORKBENCH_RUNNER_PLATFORM_URL", "http://127.0.0.1:8000"
        ).rstrip("/"),
        poll_seconds=float(os.environ.get("WORKBENCH_RUNNER_POLL_SECONDS", "5")),
        run_timeout_seconds=float(os.environ.get("WORKBENCH_RUNNER_TIMEOUT", "1800")),
        heartbeat_seconds=float(os.environ.get("WORKBENCH_RUNNER_HEARTBEAT_SECONDS", "15")),
        lease_seconds=float(os.environ.get("WORKBENCH_RUNNER_LEASE_SECONDS", "90")),
        max_attempts=int(os.environ.get("WORKBENCH_RUNNER_MAX_ATTEMPTS", "2")),
        workdir=Path(
            os.environ.get("WORKBENCH_RUNNER_WORKDIR", "storage/runner")
        ).expanduser().resolve(),
        spec_dir=Path(
            os.environ.get("WORKBENCH_RUNNER_SPEC_DIR", "specs")
        ).expanduser().resolve(),
        project_tokens=_load_project_tokens(),
    )
