from pathlib import Path

import pytest

from workbench_runner.worker import _resolve_specs


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
