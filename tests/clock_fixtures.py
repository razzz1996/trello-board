from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class FrozenClock:
    value: datetime

    def now(self) -> datetime:
        return self.value
