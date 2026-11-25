from pathlib import Path
from uuid import uuid4

import pytest

from app.db.models.run_request import RunRequest
from workbench_runner.worker import _case_target, _release, _resolve_specs


def test_resolve_specs_keeps_paths_inside_spec_dir(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    spec = spec_dir / "order.tavern.yaml"
    spec.write_text("test_name: probe\n", encoding="utf-8")
    assert _resolve_specs(["order.tavern.yaml"], spec_dir) == [str(spec.resolve())]


def test_resolve_specs_rejects_path_escape(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    with pytest.raises(ValueError):
        _resolve_specs(["../secret.yaml"], spec_dir)


def test_release_requeues_while_attempts_remain() -> None:
    request = RunRequest(
        id=uuid4(),
        project_id=uuid4(),
        status="running",
        attempt=1,
        run_external_id="RUN-OLD",
    )
    _release(request, max_attempts=2, reason="执行器重启中断")
    assert request.status == "queued"
    assert request.started_at is None
    assert request.run_external_id is None
    assert request.error == "执行器重启中断"


def test_release_fails_after_max_attempts() -> None:
    request = RunRequest(
        id=uuid4(),
        project_id=uuid4(),
        status="running",
        attempt=2,
        run_external_id="RUN-OLD",
    )
    _release(request, max_attempts=2, reason="执行器重启中断")
    assert request.status == "failed"
    assert request.finished_at is not None
    assert "已执行 2 次" in (request.error or "")


def test_case_target_maps_stored_nodeid(tmp_path: Path) -> None:
    project_id = uuid4()
    spec_dir = tmp_path / "specs" / str(project_id)
    spec_dir.mkdir(parents=True)
    spec = spec_dir / "order.yaml"
    spec.write_text("test_name: probe\n", encoding="utf-8")
    nodeid = f"storage/specs/{project_id}/order.yaml::probe"
    assert _case_target(nodeid, project_id, spec_dir) == spec.resolve()


def test_case_target_rejects_path_escape(tmp_path: Path) -> None:
    project_id = uuid4()
    spec_dir = tmp_path / "specs" / str(project_id)
    spec_dir.mkdir(parents=True)
    nodeid = f"storage/specs/{project_id}/../escape.yaml::probe"
    with pytest.raises(ValueError):
        _case_target(nodeid, project_id, spec_dir)
