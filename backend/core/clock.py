from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Protocol

from django.utils import timezone


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return timezone.now()


_SYSTEM_CLOCK = SystemClock()
_clock: ContextVar[Clock | None] = ContextVar("productivity_clock", default=None)


def now() -> datetime:
    active = _clock.get() or _SYSTEM_CLOCK
    value = active.now()
    if timezone.is_naive(value):
        raise RuntimeError("Clock returned a naive datetime.")
    return value


@contextmanager
def use_clock(clock: Clock) -> Iterator[None]:
    token = _clock.set(clock)
    try:
        yield
    finally:
        _clock.reset(token)
