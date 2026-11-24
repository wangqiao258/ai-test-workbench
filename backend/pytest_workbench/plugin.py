from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import requests

from pytest_workbench.metadata import extract_marker_metadata, index_captured_hars

TOKEN_ENV = "WORKBENCH_TOKEN"
URL_ENV = "WORKBENCH_URL"
DEFAULT_URL = "http://127.0.0.1:8000"
PHASES = ("setup", "call", "teardown")
STATUS_MAP = {
    "passed": "passed",
    "failed": "failed",
    "skipped": "skipped",
    "error": "error",
    "xfailed": "skipped",
    "xpassed": "passed",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("workbench", "AI 协同测试工作台")
    group.addoption(
        "--workbench-upload",
        action="store_true",
        default=False,
        help="把本次 pytest 运行结果上传到 AI 协同测试工作台",
    )
    group.addoption(
        "--workbench-url",
        default=os.environ.get(URL_ENV, DEFAULT_URL),
        help=f"工作台后端地址，默认 {DEFAULT_URL}，也可用环境变量 {URL_ENV}",
    )
    group.addoption(
        "--workbench-token",
        default=os.environ.get(TOKEN_ENV),
        help=f"项目级 API Token，也可用环境变量 {TOKEN_ENV}",
    )
    group.addoption(
        "--workbench-run-id",
        default=os.environ.get("WORKBENCH_RUN_ID"),
        help="外部运行 ID；不填则按时间自动生成",
    )
    group.addoption(
        "--workbench-environment",
        default=os.environ.get("WORKBENCH_ENV", ""),
        help="环境标识，例如 staging-cn-east",
    )
    group.addoption(
        "--workbench-har-dir",
        default=os.environ.get("WORKBENCH_HAR_DIR", "captured_traffic"),
        help="HAR 根目录，默认 captured_traffic；读取 pytest-traffic-capture 产物",
    )
    group.addoption(
        "--workbench-job-timeout",
        type=float,
        default=float(os.environ.get("WORKBENCH_JOB_TIMEOUT", "15")),
        help="等待 HAR 解析任务完成的秒数，0 表示不等待",
    )
    group.addoption(
        "--workbench-timeout",
        type=float,
        default=float(os.environ.get("WORKBENCH_TIMEOUT", "30")),
        help="单次 HTTP 请求超时秒数",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    if not config.getoption("workbench_upload"):
        return
    warnings.filterwarnings(
        "ignore",
        message=r"Unknown pytest\.mark\.workbench:.*",
        category=pytest.PytestUnknownMarkWarning,
    )
    token = (config.getoption("workbench_token") or "").strip()
    if not token:
        raise pytest.UsageError(
            "启用 --workbench-upload 时必须提供 --workbench-token 或环境变量 WORKBENCH_TOKEN"
        )
    # 采集与报告交给开源插件 pytest-json-report，这里只打开它并关闭落盘。
    config.option.json_report = True
    config.option.json_report_file = "none"
    config.pluginmanager.register(WorkbenchPlugin(config, token), "workbench-upload")


class WorkbenchError(RuntimeError):
    pass


class WorkbenchPlugin:
    def __init__(self, config: pytest.Config, token: str) -> None:
        self.config = config
        self.root = Path(config.rootpath)
        self.client = WorkbenchClient(
            config.getoption("workbench_url"),
            token,
            timeout=float(config.getoption("workbench_timeout")),
        )
        self.started_at = datetime.now().astimezone()
        self.run_external_id = (
            config.getoption("workbench_run_id")
            or f"RUN-{self.started_at:%Y%m%d-%H%M%S}"
        )
        self.har_dir = _resolve_path(self.root, config.getoption("workbench_har_dir"))
        self.capture_enabled = bool(config.getoption("capture_traffic", False))
        self.job_timeout = float(config.getoption("workbench_job_timeout"))
        self.report: dict[str, Any] | None = None
        self.collected_cases: list[dict[str, Any]] = []
        self.case_metadata: dict[str, dict[str, Any]] = {}

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        self.collected_cases = [self._catalog_case(item) for item in items]
        self.case_metadata = {
            case["nodeid"]: case for case in self.collected_cases
        }

    def _catalog_case(self, item: pytest.Item) -> dict[str, Any]:
        requirements, tags = extract_marker_metadata(
            marker.name for marker in item.iter_markers()
        )
        return {
            "nodeid": item.nodeid,
            "name": item.nodeid.split("::")[-1],
            "file": item.nodeid.split("::")[0],
            "tags": tags,
            "requirements": requirements,
        }

    def pytest_json_modifyreport(self, json_report: dict[str, Any]) -> None:
        self.report = json_report

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        reporter = self.config.pluginmanager.getplugin("terminalreporter")

        def line(message: str, **markup: bool) -> None:
            if reporter is not None:
                reporter.write_line(message, **markup)
            else:
                print(message)

        if self.report is None:
            line(
                "[workbench] 未拿到 pytest-json-report 报告，请确认 pytest-json-report 已安装",
                yellow=True,
            )
            return

        cases = self._run_cases(self.report)
        if not cases:
            line("[workbench] 没有可上传的用例结果", yellow=True)
            return

        catalog = self._catalog_cases(cases)
        try:
            self._upload_catalog(catalog)
        except WorkbenchError as exc:
            line(f"[workbench] 用例目录上传失败：{exc}", yellow=True)

        try:
            response = self._upload_run(self.report, cases)
        except WorkbenchError as exc:
            line(f"[workbench] 运行结果上传失败：{exc}", red=True)
            return

        run_id = response["run_id"]
        har_count, har_failed = self._upload_hars(run_id, cases)
        line(
            f"[workbench] run {self.run_external_id} 已上传："
            f"{len(cases)} 用例，{har_count} HAR，{har_failed} 失败",
            green=har_failed == 0,
            yellow=har_failed > 0,
        )
        if har_count == 0 and not self.capture_enabled:
            line(
                "[workbench] 未发现 HAR；如需自动抓包，请在命令中加 --capture-traffic",
                yellow=True,
            )

    def _run_cases(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        cases: list[dict[str, Any]] = []
        for test in report.get("tests", []):
            nodeid = str(test.get("nodeid") or "")
            if not nodeid:
                continue
            meta = self.case_metadata.get(nodeid, {})
            cases.append(
                {
                    "nodeid": nodeid,
                    "status": _test_status(test),
                    "duration_ms": _test_duration_ms(test),
                    "error": _test_error(test),
                    "logs": _test_logs(test),
                    "name": nodeid.split("::")[-1],
                    "file": nodeid.split("::")[0],
                    "tags": meta.get("tags", []),
                    "requirements": meta.get("requirements", []),
                }
            )
        return cases

    def _catalog_cases(self, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged = {case["nodeid"]: case for case in self.collected_cases}
        for case in cases:
            merged[case["nodeid"]] = {
                "nodeid": case["nodeid"],
                "name": case["name"],
                "file": case["file"],
                "tags": case["tags"],
                "requirements": case["requirements"],
            }
        return list(merged.values())

    def _upload_catalog(self, cases: list[dict[str, Any]]) -> None:
        self.client.post_json("/ingest/v1/catalog", {"cases": cases})

    def _upload_run(
        self, report: dict[str, Any], cases: list[dict[str, Any]]
    ) -> dict[str, Any]:
        created = float(report.get("created") or time.time())
        started_at = datetime.fromtimestamp(created, tz=timezone.utc).astimezone()
        payload = {
            "run": {
                "external_id": self.run_external_id,
                "started_at": started_at.isoformat(),
                "duration_ms": int(float(report.get("duration") or 0) * 1000),
                "branch": _git_value(self.root, "rev-parse", "--abbrev-ref", "HEAD"),
                "commit": _git_value(self.root, "rev-parse", "--short", "HEAD"),
                "environment": self.config.getoption("workbench_environment"),
            },
            "cases": cases,
        }
        return self.client.post_json("/ingest/v1/runs", payload)

    def _upload_hars(self, run_id: str, cases: list[dict[str, Any]]) -> tuple[int, int]:
        uploaded = 0
        failed = 0
        reporter = self.config.pluginmanager.getplugin("terminalreporter")
        capture_index = index_captured_hars(self.har_dir)
        for case in cases:
            nodeid = case["nodeid"]
            har_path = capture_index.get(nodeid)
            if har_path is None:
                continue
            try:
                response = self.client.post_har(run_id, nodeid, har_path)
            except WorkbenchError as exc:
                failed += 1
                _warn(reporter, f"[workbench] HAR 上传失败 {nodeid}：{exc}")
                continue
            uploaded += 1
            job_id = response.get("job_id")
            if job_id and self.job_timeout > 0:
                job = self._wait_job(job_id)
                if job is not None and job.get("status") == "failed":
                    failed += 1
                    _warn(
                        reporter,
                        f"[workbench] HAR 解析失败 {nodeid}：{job.get('error')}",
                    )
        return uploaded, failed

    def _wait_job(self, job_id: str) -> dict[str, Any] | None:
        deadline = time.monotonic() + self.job_timeout
        while time.monotonic() < deadline:
            job = self.client.get_json(f"/ingest/v1/jobs/{job_id}")
            if job.get("status") in ("succeeded", "failed"):
                return job
            time.sleep(0.3)
        return None


class WorkbenchClient:
    def __init__(self, base_url: str, token: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["X-Project-Token"] = token

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Idempotency-Key": _idempotency_key(body),
        }
        return self._send("POST", path, data=body, headers=headers)

    def get_json(self, path: str) -> dict[str, Any]:
        return self._send("GET", path)

    def post_har(self, run_id: str, nodeid: str, har_path: Path) -> dict[str, Any]:
        data = har_path.read_bytes()
        return self._send(
            "POST",
            f"/ingest/v1/runs/{run_id}/artifacts",
            data={"kind": "har", "nodeid": nodeid},
            files={"file": (har_path.name, data, "application/json")},
            headers={
                "Idempotency-Key": _idempotency_key(
                    nodeid.encode("utf-8") + data
                )
            },
        )

    def _send(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.session.request(
                method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            response = exc.response
            detail = response.text[:500] if response is not None else ""
            status = response.status_code if response is not None else "?"
            raise WorkbenchError(
                f"{method} {path} 返回 HTTP {status}：{detail}"
            ) from exc
        except requests.RequestException as exc:
            raise WorkbenchError(f"{method} {path} 连接失败：{exc}") from exc


def _test_status(test: dict[str, Any]) -> str:
    outcome = str(test.get("outcome") or "")
    if outcome in STATUS_MAP:
        return STATUS_MAP[outcome]
    phases = [str((test.get(phase) or {}).get("outcome") or "") for phase in PHASES]
    if "failed" in phases:
        return "failed" if (test.get("call") or {}).get("outcome") == "failed" else "error"
    if "error" in phases:
        return "error"
    if "skipped" in phases:
        return "skipped"
    return "passed"


def _test_duration_ms(test: dict[str, Any]) -> int:
    seconds = 0.0
    for phase in PHASES:
        seconds += float((test.get(phase) or {}).get("duration") or 0)
    return int(seconds * 1000)


def _test_error(test: dict[str, Any]) -> str | None:
    for phase in PHASES:
        stage = test.get(phase) or {}
        if stage.get("outcome") in ("failed", "error") and stage.get("longrepr"):
            return str(stage["longrepr"])
    return None


def _test_logs(test: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for phase in PHASES:
        stage = test.get(phase) or {}
        for record in stage.get("log") or []:
            level = record.get("levelname") or "INFO"
            logger = record.get("name") or "root"
            message = record.get("msg") or ""
            lines.append(f"[{phase}] {level} {logger}: {message}")
        for stream in ("stdout", "stderr"):
            text = stage.get(stream)
            if text:
                lines.extend(
                    f"[{phase}][{stream}] {item}"
                    for item in str(text).splitlines()
                    if item.strip()
                )
    return lines


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _git_value(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _idempotency_key(body: bytes) -> str:
    return "wb-" + hashlib.sha256(body).hexdigest()[:48]


def _warn(reporter: Any, message: str) -> None:
    if reporter is not None:
        reporter.write_line(message, yellow=True)
    else:
        print(message)
