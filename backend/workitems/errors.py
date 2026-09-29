from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DomainError(Exception):
    code: str
    message: str
    status: int = 400
    field_errors: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message
