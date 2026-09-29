from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator, FormatChecker

SECRET_KEY_PATTERN = re.compile(r"(password|passwd|token|secret|api[_-]?key)", re.IGNORECASE)


class ConfigValidationError(ValueError):
    pass


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigValidationError(f"Cannot read valid JSON from {path}: {exc}") from exc


def _assert_no_secret_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET_KEY_PATTERN.search(str(key)):
                raise ConfigValidationError(
                    f"Secret-like key is not allowed in deployment JSON: {path}.{key}"
                )
            _assert_no_secret_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_secret_keys(child, f"{path}[{index}]")


def validate_files(config_path: Path, schema_path: Path) -> dict[str, Any]:
    config = _load_json(config_path)
    schema = _load_json(schema_path)
    if not isinstance(config, dict) or not isinstance(schema, dict):
        raise ConfigValidationError("Configuration and schema must both be JSON objects.")

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(config), key=lambda item: list(item.absolute_path))
    if errors:
        first = errors[0]
        location = "$" + "".join(f"[{part!r}]" for part in first.absolute_path)
        raise ConfigValidationError(f"{location}: {first.message}")

    _assert_no_secret_keys(config)
    try:
        ZoneInfo(str(config["timezone"]))
    except ZoneInfoNotFoundError as exc:
        raise ConfigValidationError(f"Invalid IANA timezone: {config['timezone']}") from exc

    for raw in config["allowed_client_cidrs"]:
        try:
            ipaddress.ip_network(raw, strict=False)
        except ValueError as exc:
            raise ConfigValidationError(f"Invalid CIDR in allowed_client_cidrs: {raw}") from exc

    if config["workday_start"] >= config["workday_end"]:
        raise ConfigValidationError("workday_start must be before workday_end.")

    if config["environment"] == "pilot":
        required = ("private_base_url", "manager_user_id", "backup_target")
        missing = [key for key in required if not config.get(key)]
        if not config["allowed_client_cidrs"]:
            missing.append("allowed_client_cidrs")
        if missing:
            raise ConfigValidationError("Pilot configuration is missing: " + ", ".join(missing))

    if config["restore_mode"] and config["slack_mode"] == "live":
        raise ConfigValidationError("restore_mode cannot be combined with slack_mode=live.")

    return config
