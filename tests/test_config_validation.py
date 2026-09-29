from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.config_validation import ConfigValidationError, validate_files


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _base_config() -> dict:
    return json.loads((Path("config") / "example.json").read_text(encoding="utf-8-sig"))


def test_example_config_is_valid(tmp_path: Path) -> None:
    config_path = tmp_path / "deployment.json"
    _write(config_path, _base_config())

    value = validate_files(config_path, Path("config") / "deployment.schema.json")

    assert value["slack_mode"] == "off"
    assert value["timezone"] == "Asia/Manila"


def test_unknown_config_key_fails_closed(tmp_path: Path) -> None:
    value = _base_config()
    value["surprise"] = True
    config_path = tmp_path / "deployment.json"
    _write(config_path, value)

    with pytest.raises(ConfigValidationError, match="Additional properties"):
        validate_files(config_path, Path("config") / "deployment.schema.json")


def test_secret_like_config_key_is_rejected(tmp_path: Path) -> None:
    value = _base_config()
    value["backup_target"] = None
    value["allowed_client_cidrs"] = []
    value["private_base_url"] = None
    value["manager_user_id"] = None
    value["token"] = "must-not-be-here"  # noqa: S105 - intentionally verifies rejection
    config_path = tmp_path / "deployment.json"
    _write(config_path, value)

    with pytest.raises(ConfigValidationError):
        validate_files(config_path, Path("config") / "deployment.schema.json")


def test_pilot_requires_private_operational_inputs(tmp_path: Path) -> None:
    value = _base_config()
    value["environment"] = "pilot"
    config_path = tmp_path / "deployment.json"
    _write(config_path, value)

    with pytest.raises(ConfigValidationError, match="Pilot configuration is missing"):
        validate_files(config_path, Path("config") / "deployment.schema.json")


def test_restore_mode_forbids_live_slack(tmp_path: Path) -> None:
    value = _base_config()
    value["restore_mode"] = True
    value["slack_mode"] = "live"
    config_path = tmp_path / "deployment.json"
    _write(config_path, value)

    with pytest.raises(ConfigValidationError, match="restore_mode"):
        validate_files(config_path, Path("config") / "deployment.schema.json")
