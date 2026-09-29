from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

SECRET_PATTERN = re.compile(r"(?i)(password|passwd|token|secret|api[_-]?key)\s*[:=]\s*([^\s,;]+)")


def redact(value: str) -> str:
    return SECRET_PATTERN.sub(r"\1=[REDACTED]", value)


class RedactingJsonFormatter(logging.Formatter):
    SAFE_EXTRA = (
        "request_id",
        "task_id",
        "board_id",
        "job_id",
        "notification_id",
        "event_type",
        "error_code",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key in self.SAFE_EXTRA:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = str(value)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
