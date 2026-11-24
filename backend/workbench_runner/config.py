from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunnerSettings:
    platform_url: str
    poll_seconds: float
    run_timeout_seconds: float
    workdir: Path
    spec_dir: Path
    project_tokens: dict[str, str]


def _load_project_tokens() -> dict[str, str]:
    raw = os.environ.get("WORKBENCH_PROJECT_TOKENS", "").strip()
    if raw:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("WORKBENCH_PROJECT_TOKENS 必须是 projectKey -> token 的 JSON 对象")
        return {
            str(key): str(value)
            for key, value in data.items()
            if str(key).strip() and str(value).strip()
        }
    token = os.environ.get("WORKBENCH_PROJECT_TOKEN", "").strip()
    key = os.environ.get("WORKBENCH_PROJECT_KEY", "").strip()
    return {key: token} if key and token else {}


def load_settings() -> RunnerSettings:
    return RunnerSettings(
        platform_url=os.environ.get(
            "WORKBENCH_RUNNER_PLATFORM_URL", "http://127.0.0.1:8000"
        ).rstrip("/"),
        poll_seconds=float(os.environ.get("WORKBENCH_RUNNER_POLL_SECONDS", "5")),
        run_timeout_seconds=float(os.environ.get("WORKBENCH_RUNNER_TIMEOUT", "1800")),
        workdir=Path(
            os.environ.get("WORKBENCH_RUNNER_WORKDIR", "storage/runner")
        ).expanduser().resolve(),
        spec_dir=Path(
            os.environ.get("WORKBENCH_RUNNER_SPEC_DIR", "specs")
        ).expanduser().resolve(),
        project_tokens=_load_project_tokens(),
    )
