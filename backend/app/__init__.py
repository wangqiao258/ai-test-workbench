"""版本号来源：APP_VERSION 环境变量 → 运行时 git tag → 安装元数据。"""

import os
import re
import subprocess
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DESCRIBE = re.compile(r"^v?(\d+\.\d+\.\d+)(?:-(\d+)-g([0-9a-f]+))?(-dirty)?$")


def _installed_version() -> str | None:
    try:
        return installed_version("ai-test-workbench-backend")
    except PackageNotFoundError:
        return None


def _normalize(raw: str) -> str:
    """把 git describe 结果转成与前端一致的格式：0.2.0+3.sha.dirty。"""
    matched = _DESCRIBE.match(raw)
    if not matched:
        return raw.removeprefix("v")
    base, ahead, sha, dirty = matched.groups()
    if not sha:
        return f"{base}{'+dirty' if dirty else ''}"
    return f"{base}+{ahead}.{sha}{'.dirty' if dirty else ''}"


def _git_version() -> str | None:
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    raw = result.stdout.strip()
    if result.returncode != 0 or not raw:
        return None
    return _normalize(raw)


def _resolve_version() -> str:
    return (
        os.environ.get("APP_VERSION", "").strip()
        or _git_version()
        or _installed_version()
        or "0.0.0+unknown"
    )


__version__ = _resolve_version()
