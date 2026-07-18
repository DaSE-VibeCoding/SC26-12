from pathlib import Path, PureWindowsPath

import pytest

from fintrace.shared.file_store import read_json, write_json
from fintrace.shared.paths import (
    configured_path,
    get_input_example_path,
    get_project_root,
    load_path_config,
    project_relative,
)


def test_project_root_contains_configuration() -> None:
    assert (get_project_root() / "configs" / "paths.yaml").is_file()


def test_required_path_configuration_is_loaded() -> None:
    config = load_path_config()
    assert config["data_dir"] == "data"
    assert configured_path("data_dir") == get_project_root() / "data"


def test_chinese_input_filename_is_resolved() -> None:
    filename = "贵州茅台：贵州茅台2026年第一季度报告.pdf"
    assert get_input_example_path(filename).is_file()


def test_windows_path_components_are_not_dropped() -> None:
    windows_path = PureWindowsPath("data\\raw_pdfs\\600519\\报告.pdf")
    assert windows_path.parts[-2:] == ("600519", "报告.pdf")


def test_atomic_json_round_trip(tmp_path: Path) -> None:
    destination = tmp_path / "中文目录" / "结果.json"
    write_json(destination, {"company_code": "000001", "name": "平安银行"})
    assert read_json(destination)["company_code"] == "000001"
    assert not list(destination.parent.glob(f".{destination.name}.*"))


def test_unknown_configuration_key_is_rejected() -> None:
    with pytest.raises(Exception, match="Unknown path configuration key"):
        configured_path("does_not_exist")


def test_runtime_paths_are_serialized_relative_to_project() -> None:
    assert project_relative(configured_path("outputs_dir")) == "data/outputs"
