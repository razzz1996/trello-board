from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from notifications.obligations import next_work_window
from schedules.services import ScheduleError, _validate_effective_period

MANILA = ZoneInfo("Asia/Manila")


@pytest.mark.parametrize(
    ("frequency", "value"),
    [
        ("daily", "2026-09-29"),
        ("weekly", "2026-W40"),
        ("monthly", "2026-09"),
    ],
)
def test_effective_period_accepts_canonical_values(frequency: str, value: str) -> None:
    assert (
        _validate_effective_period(
            frequency=frequency,
            value=value,
            cursor="",
        )
        == value
    )


@pytest.mark.parametrize(
    ("frequency", "value"),
    [
        ("daily", "2026-9-29"),
        ("weekly", "2026-W4"),
        ("monthly", "2026-9"),
        ("weekly", "not-a-week"),
    ],
)
def test_effective_period_rejects_noncanonical_values(frequency: str, value: str) -> None:
    with pytest.raises(ScheduleError):
        _validate_effective_period(
            frequency=frequency,
            value=value,
            cursor="",
        )


def test_effective_period_must_be_after_issued_cursor() -> None:
    with pytest.raises(ScheduleError, match="last issued"):
        _validate_effective_period(
            frequency="daily",
            value="2026-09-29",
            cursor="2026-09-29",
        )


def test_revision_boundary_must_advance() -> None:
    with pytest.raises(ScheduleError, match="prior revision"):
        _validate_effective_period(
            frequency="monthly",
            value="2026-10",
            cursor="",
            previous="2026-10",
        )


def test_after_hours_moves_to_next_workday_start() -> None:
    friday_evening = datetime(2026, 10, 2, 19, 15, tzinfo=MANILA)
    result = next_work_window(friday_evening)

    assert result == datetime(2026, 10, 5, 8, 0, tzinfo=MANILA)


def test_before_hours_moves_to_same_workday_start() -> None:
    tuesday_early = datetime(2026, 9, 29, 6, 30, tzinfo=MANILA)
    result = next_work_window(tuesday_early)

    assert result == datetime(2026, 9, 29, 8, 0, tzinfo=MANILA)


def test_work_hours_keep_original_instant() -> None:
    tuesday = datetime(2026, 9, 29, 11, 30, tzinfo=MANILA)

    assert next_work_window(tuesday) is tuesday
