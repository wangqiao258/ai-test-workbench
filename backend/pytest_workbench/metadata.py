from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

REQUIREMENT_MARKER_PREFIX = "workbench:requirement:"
TAG_MARKER_PREFIX = "workbench:tag:"


def extract_marker_metadata(marker_names: Iterable[str]) -> tuple[list[str], list[str]]:
    """从 pytest marks 中提取 Tavern 用例的 requirement 和 tags。"""
    requirements: list[str] = []
    tags: list[str] = []
    for name in marker_names:
        if not isinstance(name, str):
            continue
        if name.startswith(REQUIREMENT_MARKER_PREFIX):
            value = name[len(REQUIREMENT_MARKER_PREFIX) :].strip()
            if value:
                requirements.append(value)
        elif name.startswith(TAG_MARKER_PREFIX):
            value = name[len(TAG_MARKER_PREFIX) :].strip()
            if value:
                tags.append(value)
    return list(dict.fromkeys(requirements)), list(dict.fromkeys(tags))


def index_captured_hars(har_dir: Path) -> dict[str, Path]:
    """按 pytest-traffic-capture 写入的 log._test.nodeid 建立 HAR 索引。"""
    index: dict[str, Path] = {}
    if not har_dir.is_dir():
        return index
    for path in har_dir.glob("traffic_*.har"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        log = data.get("log") if isinstance(data, dict) else None
        test_meta = log.get("_test") if isinstance(log, dict) else None
        nodeid = test_meta.get("nodeid") if isinstance(test_meta, dict) else None
        if isinstance(nodeid, str) and nodeid:
            index[nodeid] = path
    return index
