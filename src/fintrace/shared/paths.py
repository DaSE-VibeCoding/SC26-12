"""Resolve every project path from one configuration source."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from fintrace.shared.exceptions import InputFileNotFoundError, PathConfigError

CONFIG_RELATIVE_PATH = Path("configs/paths.yaml")
REQUIRED_KEYS = {
    "lookup_dir",
    "input_example_dir",
    "data_dir",
    "processed_dir",
    "outputs_dir",
    "indexes_dir",
    "logs_dir",
    "company_master_file",
    "company_master_desc_file",
    "cninfo_address_file",
}


def _discovered_root() -> Path:
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def get_project_root() -> Path:
    override = os.environ.get("PROJECT_ROOT")
    root = Path(override).expanduser() if override else _discovered_root()
    root = root.resolve()
    config_file = root / CONFIG_RELATIVE_PATH
    if not config_file.is_file():
        raise PathConfigError(
            f"Path configuration does not exist: {config_file}",
            step="load_path_config",
        )
    return root


@lru_cache(maxsize=1)
def load_path_config() -> dict[str, Any]:
    config_file = get_project_root() / CONFIG_RELATIVE_PATH
    try:
        payload = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PathConfigError(
            f"Could not read path configuration: {config_file}",
            step="load_path_config",
            details={"reason": str(exc)},
        ) from exc
    if not isinstance(payload, dict):
        raise PathConfigError("Path configuration must be a YAML mapping.", step="load_path_config")
    missing = sorted(REQUIRED_KEYS - payload.keys())
    if missing:
        raise PathConfigError(
            f"Path configuration is missing keys: {', '.join(missing)}",
            step="load_path_config",
            details={"missing_keys": missing},
        )
    return payload


def configured_path(key: str) -> Path:
    config = load_path_config()
    if key not in config:
        raise PathConfigError(f"Unknown path configuration key: {key}", step="resolve_path")
    value = config[key]
    if not isinstance(value, str) or not value.strip():
        raise PathConfigError(f"Path configuration '{key}' must be a string.", step="resolve_path")
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (get_project_root() / path).resolve()


def require_file(key: str) -> Path:
    path = configured_path(key)
    if not path.is_file():
        raise InputFileNotFoundError(
            f"Required file for '{key}' does not exist: {path}",
            step="validate_inputs",
            details={"config_key": key},
        )
    return path


def get_lookup_path(name: str) -> Path:
    return configured_path("lookup_dir") / name


def get_input_example_path(name: str) -> Path:
    return configured_path("input_example_dir") / name


def get_raw_report_path(company_code: str, filename: str) -> Path:
    return configured_path("raw_reports_dir") / company_code / filename


def get_processed_dir(
    feature: str, company_code: str, run_id: str, step_name: str | None = None
) -> Path:
    path = configured_path("processed_dir") / feature / company_code / run_id
    return path / step_name if step_name else path


def get_output_dir(feature: str, company_code: str, run_id: str) -> Path:
    return configured_path("outputs_dir") / feature / company_code / run_id


def ensure_runtime_directories() -> list[Path]:
    keys = ("data_dir", "processed_dir", "outputs_dir", "indexes_dir", "logs_dir")
    result = []
    for key in keys:
        path = configured_path(key)
        path.mkdir(parents=True, exist_ok=True)
        result.append(path)
    return result


def project_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(get_project_root()).as_posix()
    except ValueError as exc:
        raise PathConfigError(
            f"Path is outside the project root: {path}",
            step="serialize_path",
        ) from exc


def clear_path_caches() -> None:
    get_project_root.cache_clear()
    load_path_config.cache_clear()
