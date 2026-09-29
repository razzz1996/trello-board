from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from schedules.engine import RuleError, generate_preview


def monthly_rule(anchor: str, year_day: int = 31):
    return {
        "frequency": "monthly",
        "interval": 1,
        "anchor_month": anchor,
        "timezone": "Asia/Manila",
        "release_time": "08:00",
        "due_time": "17:00",
        "workdays_iso": [1, 2, 3, 4, 5],
        "holidays": [],
        "shift_policy": "none",
        "release_rule": {"kind": "day", "day": year_day},
        "due_rule": {"kind": "day", "day": year_day},
    }


def test_monthly_day_31_clamps_non_leap_february():
    preview = generate_preview(
        monthly_rule("2027-02"),
        after=date(2027, 1, 31),
        count=1,
    )
    assert preview[0].period_key == "2027-02"
    assert preview[0].base_release_date == date(2027, 2, 28)


def test_monthly_day_31_clamps_leap_february():
    preview = generate_preview(
        monthly_rule("2028-02"),
        after=date(2028, 1, 31),
        count=1,
    )
    assert preview[0].base_release_date == date(2028, 2, 29)


def daily_rule(**overrides):
    rule = {
        "frequency": "daily",
        "interval": 1,
        "anchor_date": "2026-10-02",
        "timezone": "Asia/Manila",
        "release_time": "08:00",
        "due_time": "17:00",
        "workdays_iso": [1, 2, 3, 4, 5],
        "holidays": [],
        "shift_policy": "none",
    }
    rule.update(overrides)
    return rule


def test_weekday_filter_after_friday_october_2():
    preview = generate_preview(
        daily_rule(weekdays_iso=[1, 2, 3, 4, 5]),
        after=date(2026, 10, 2),
        count=1,
    )
    assert preview[0].base_release_date == date(2026, 10, 5)
    assert preview[0].period_key == "2026-10-05"


def test_distinct_periods_can_shift_to_same_release_date():
    preview = generate_preview(
        daily_rule(
            holidays=["2026-10-02"],
            shift_policy="next_workday",
        ),
        after=date(2026, 10, 1),
        count=2,
    )
    assert [item.period_key for item in preview] == [
        "2026-10-02",
        "2026-10-03",
    ]
    assert [item.adjusted_release_date for item in preview] == [
        date(2026, 10, 5),
        date(2026, 10, 5),
    ]


def test_planned_pause_excludes_base_periods_without_backfill():
    preview = generate_preview(
        daily_rule(),
        after=date(2026, 10, 4),
        count=2,
        pauses=[{"start": "2026-10-05", "end": "2026-10-08"}],
    )
    assert [item.period_key for item in preview] == [
        "2026-10-08",
        "2026-10-09",
    ]


def test_empty_work_calendar_is_rejected():
    with pytest.raises(RuleError, match="workdays_iso"):
        generate_preview(
            daily_rule(workdays_iso=[]),
            after=date(2026, 10, 1),
        )


def test_due_before_release_is_rejected():
    with pytest.raises(RuleError, match="before release"):
        generate_preview(
            daily_rule(
                release_time="17:00",
                due_time="08:00",
            ),
            after=date(2026, 10, 1),
            count=1,
        )


def test_dst_gap_advances_to_first_valid_instant():
    rule = daily_rule(
        anchor_date="2027-03-14",
        timezone="America/New_York",
        release_time="02:30",
        due_time="17:00",
        workdays_iso=[1, 2, 3, 4, 5, 6, 7],
    )
    preview = generate_preview(
        rule,
        after=datetime(2027, 3, 13, 0, 0, tzinfo=ZoneInfo("America/New_York")),
        count=1,
    )
    assert preview[0].release_at.hour == 3
    assert preview[0].release_at.minute == 0
    assert any("nonexistent local time" in note for note in preview[0].explanations)


def test_dst_fold_chooses_first_occurrence():
    rule = daily_rule(
        anchor_date="2027-11-07",
        timezone="America/New_York",
        release_time="01:30",
        due_time="17:00",
        workdays_iso=[1, 2, 3, 4, 5, 6, 7],
    )
    preview = generate_preview(
        rule,
        after=datetime(2027, 11, 6, 0, 0, tzinfo=ZoneInfo("America/New_York")),
        count=1,
    )
    assert preview[0].release_at.fold == 0
    assert any("ambiguous local time" in note for note in preview[0].explanations)
