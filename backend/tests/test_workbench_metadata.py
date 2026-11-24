import json
from pathlib import Path

from pytest_workbench.metadata import extract_marker_metadata, index_captured_hars


def test_extract_marker_metadata_dedupes_and_ignores_other_marks() -> None:
    requirements, tags = extract_marker_metadata(
        [
            "workbench:requirement:REQ-E2E-STOCK-02",
            "workbench:requirement:REQ-E2E-STOCK-02",
            "workbench:tag:订单",
            "workbench:tag:订单",
            "workbench:tag:回归",
            "slow",
            "workbench:requirement:",
        ]
    )
    assert requirements == ["REQ-E2E-STOCK-02"]
    assert tags == ["订单", "回归"]


def test_index_captured_hars_by_test_metadata(tmp_path: Path) -> None:
    har_dir = tmp_path / "captured_traffic"
    har_dir.mkdir()
    nodeid = "test_order.tavern.yaml::创建订单成功"
    har = har_dir / "traffic_test_order_tavern_yaml_ab12cd34.har"
    har.write_text(
        json.dumps({"log": {"_test": {"nodeid": nodeid}, "entries": []}}),
        encoding="utf-8",
    )
    assert index_captured_hars(har_dir) == {nodeid: har}


def test_index_captured_hars_ignores_invalid_documents(tmp_path: Path) -> None:
    har_dir = tmp_path / "captured_traffic"
    har_dir.mkdir()
    (har_dir / "traffic_broken.har").write_text("not-json", encoding="utf-8")
    assert index_captured_hars(har_dir) == {}
