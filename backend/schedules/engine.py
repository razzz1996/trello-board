from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class RuleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PreviewOccurrence:
    period_key: str
    base_release_date: date
    adjusted_release_date: date
    adjusted_due_date: date
    release_at: datetime
    due_at: datetime
    explanations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in (
            "base_release_date",
            "adjusted_release_date",
            "adjusted_due_date",
        ):
            value[key] = value[key].isoformat()
        value["release_at"] = self.release_at.isoformat()
        value["due_at"] = self.due_at.isoformat()
        value["explanations"] = list(self.explanations)
        return value


def _date(value: Any, field: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise RuleError(f"{field} must be an ISO date.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RuleError(f"{field} must be an ISO date.") from exc


def _time(value: Any, field: str) -> time:
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    if not isinstance(value, str):
        raise RuleError(f"{field} must be HH:MM.")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise RuleError(f"{field} must be HH:MM.") from exc
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise RuleError(f"{field} must be a local HH:MM value.")
    return parsed


def _zone(value: Any) -> ZoneInfo:
    if not isinstance(value, str) or not value:
        raise RuleError("timezone must be a valid IANA zone.")
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise RuleError("timezone must be a valid IANA zone.") from exc


def _calendar(rule: dict[str, Any]) -> tuple[set[int], set[date]]:
    raw_workdays = rule.get("workdays_iso", [1, 2, 3, 4, 5])
    if not isinstance(raw_workdays, list):
        raise RuleError("workdays_iso must be a list.")
    workdays = {int(value) for value in raw_workdays}
    if not workdays or any(value < 1 or value > 7 for value in workdays):
        raise RuleError("workdays_iso must contain ISO weekdays 1 through 7.")
    raw_holidays = rule.get("holidays", [])
    if not isinstance(raw_holidays, list):
        raise RuleError("holidays must be a list.")
    holidays = {_date(value, "holiday") for value in raw_holidays}
    return workdays, holidays


def _is_workday(value: date, workdays: set[int], holidays: set[date]) -> bool:
    return value.isoweekday() in workdays and value not in holidays


def _shift_date(
    value: date,
    policy: str,
    workdays: set[int],
    holidays: set[date],
) -> tuple[date, str | None]:
    if policy == "none":
        return value, None
    if policy not in {"previous_workday", "next_workday"}:
        raise RuleError("shift_policy must be none, previous_workday or next_workday.")
    if _is_workday(value, workdays, holidays):
        return value, None

    direction = -1 if policy == "previous_workday" else 1
    candidate = value
    for _ in range(366):
        candidate += timedelta(days=direction)
        if _is_workday(candidate, workdays, holidays):
            return candidate, f"{value.isoformat()} shifted to {candidate.isoformat()}"
    raise RuleError("No eligible workday found within 366 days.")


def _localize(naive: datetime, zone: ZoneInfo) -> tuple[datetime, str | None]:
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)

    def valid(candidate: datetime) -> bool:
        roundtrip = candidate.astimezone(UTC).astimezone(zone)
        return roundtrip.replace(tzinfo=None) == naive

    first_valid = valid(first)
    second_valid = valid(second)
    if first_valid:
        if second_valid and first.utcoffset() != second.utcoffset():
            return first, "ambiguous local time resolved to first occurrence"
        return first, None
    if second_valid:
        return second, None

    candidate = naive
    for _ in range(181):
        candidate += timedelta(minutes=1)
        localized, note = _localize_if_valid(candidate, zone)
        if localized is not None:
            return localized, f"nonexistent local time advanced to {candidate.time():%H:%M}"
    raise RuleError("No valid local time found within three hours after DST gap.")


def _localize_if_valid(
    naive: datetime,
    zone: ZoneInfo,
) -> tuple[datetime | None, str | None]:
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    first_roundtrip = first.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    second_roundtrip = second.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    if first_roundtrip == naive:
        if second_roundtrip == naive and first.utcoffset() != second.utcoffset():
            return first, "ambiguous local time resolved to first occurrence"
        return first, None
    if second_roundtrip == naive:
        return second, None
    return None, None


def _at_local(
    value: date,
    local_time: time,
    zone: ZoneInfo,
) -> tuple[datetime, str | None]:
    return _localize(datetime.combine(value, local_time), zone)


def _month_add(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute = year * 12 + (month - 1) + offset
    return absolute // 12, absolute % 12 + 1


def _month_day_clamped(year: int, month: int, day_number: int) -> date:
    if day_number < 1 or day_number > 31:
        raise RuleError("Monthly day number must be between 1 and 31.")
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day_number, last))


def _monthly_date(
    year: int,
    month: int,
    spec: dict[str, Any],
    workdays: set[int],
    holidays: set[date],
) -> date:
    kind = spec.get("kind")
    if kind == "day":
        try:
            return _month_day_clamped(year, month, int(spec["day"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuleError("Monthly day rule requires day 1 through 31.") from exc
    last = calendar.monthrange(year, month)[1]
    if kind == "first_working_day":
        candidates = range(1, last + 1)
    elif kind == "last_working_day":
        candidates = range(last, 0, -1)
    else:
        raise RuleError("Monthly rule kind must be day, first_working_day or last_working_day.")
    for day_number in candidates:
        candidate = date(year, month, day_number)
        if _is_workday(candidate, workdays, holidays):
            return candidate
    raise RuleError("No eligible workday exists in the requested month.")


def _pause_bounds(value: Any) -> tuple[date, date]:
    if isinstance(value, dict):
        return _date(value.get("start"), "pause start"), _date(
            value.get("end"),
            "pause end",
        )
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return _date(value[0], "pause start"), _date(value[1], "pause end")
    raise RuleError("Pause intervals must provide start and end dates.")


def _is_paused(base_release: date, pauses: list[Any]) -> bool:
    for value in pauses:
        start, end = _pause_bounds(value)
        if end <= start:
            raise RuleError("Pause end must be after pause start.")
        if start <= base_release < end:
            return True
    return False


def _cutoff(after: date | datetime, zone: ZoneInfo) -> datetime:
    if isinstance(after, datetime):
        if after.tzinfo is None:
            raise RuleError("Preview cutoff datetime must include a timezone.")
        return after.astimezone(zone)
    localized, _ = _at_local(after, time(23, 59, 59), zone)
    return localized


def _build_occurrence(
    *,
    period_key: str,
    base_release: date,
    base_due: date,
    rule: dict[str, Any],
    zone: ZoneInfo,
    workdays: set[int],
    holidays: set[date],
) -> PreviewOccurrence:
    policy = str(rule.get("shift_policy", "none"))
    release_date, release_shift = _shift_date(
        base_release,
        policy,
        workdays,
        holidays,
    )
    due_date, due_shift = _shift_date(
        base_due,
        policy,
        workdays,
        holidays,
    )
    release_at, release_time_note = _at_local(
        release_date,
        _time(rule.get("release_time", "08:00"), "release_time"),
        zone,
    )
    due_at, due_time_note = _at_local(
        due_date,
        _time(rule.get("due_time", "17:00"), "due_time"),
        zone,
    )
    if due_at < release_at:
        raise RuleError("Adjusted due time cannot be before release time.")

    notes = tuple(
        note
        for note in (
            release_shift,
            due_shift,
            release_time_note,
            due_time_note,
        )
        if note
    )
    return PreviewOccurrence(
        period_key=period_key,
        base_release_date=base_release,
        adjusted_release_date=release_date,
        adjusted_due_date=due_date,
        release_at=release_at,
        due_at=due_at,
        explanations=notes,
    )


def _daily_periods(
    rule: dict[str, Any],
    cutoff: datetime,
) -> Any:
    anchor = _date(rule.get("anchor_date"), "anchor_date")
    interval = int(rule.get("interval", 1))
    if interval < 1:
        raise RuleError("Daily interval must be positive.")
    raw_weekdays = rule.get("weekdays_iso")
    weekdays = None
    if raw_weekdays is not None:
        if not isinstance(raw_weekdays, list) or not raw_weekdays:
            raise RuleError("weekdays_iso must be a nonempty list when provided.")
        weekdays = {int(value) for value in raw_weekdays}
        if any(value < 1 or value > 7 for value in weekdays):
            raise RuleError("weekdays_iso values must be between 1 and 7.")
    end_date = _date(rule["end_date"], "end_date") if rule.get("end_date") else None

    candidate = anchor
    for _ in range(100000):
        if end_date is not None and candidate > end_date:
            return
        if weekdays is None or candidate.isoweekday() in weekdays:
            yield candidate.isoformat(), candidate, candidate
        candidate += timedelta(days=interval)
    raise RuleError("Daily schedule exceeded the bounded preview search.")


def _weekly_periods(rule: dict[str, Any]) -> Any:
    anchor = _date(rule.get("anchor_date"), "anchor_date")
    interval = int(rule.get("interval", 1))
    if interval < 1:
        raise RuleError("Weekly interval must be positive.")
    release_weekday = int(rule.get("release_weekday", anchor.isoweekday()))
    due_weekday = int(rule.get("due_weekday", release_weekday))
    if release_weekday not in range(1, 8) or due_weekday not in range(1, 8):
        raise RuleError("Weekly release and due weekdays must be between 1 and 7.")
    end_date = _date(rule["end_date"], "end_date") if rule.get("end_date") else None
    anchor_monday = anchor - timedelta(days=anchor.isoweekday() - 1)

    week_index = 0
    for _ in range(100000):
        monday = anchor_monday + timedelta(weeks=week_index * interval)
        release = monday + timedelta(days=release_weekday - 1)
        due = monday + timedelta(days=due_weekday - 1)
        if end_date is not None and release > end_date:
            return
        iso_year, iso_week, _ = monday.isocalendar()
        yield f"{iso_year:04d}-W{iso_week:02d}", release, due
        week_index += 1
    raise RuleError("Weekly schedule exceeded the bounded preview search.")


def _anchor_month(rule: dict[str, Any]) -> tuple[int, int]:
    value = rule.get("anchor_month")
    if isinstance(value, str):
        try:
            year_text, month_text = value.split("-", 1)
            year, month = int(year_text), int(month_text)
        except (ValueError, AttributeError) as exc:
            raise RuleError("anchor_month must use YYYY-MM.") from exc
        if month not in range(1, 13):
            raise RuleError("anchor_month must use YYYY-MM.")
        return year, month
    if rule.get("anchor_date"):
        anchor = _date(rule["anchor_date"], "anchor_date")
        return anchor.year, anchor.month
    raise RuleError("Monthly rules require anchor_month or anchor_date.")


def _monthly_periods(
    rule: dict[str, Any],
    workdays: set[int],
    holidays: set[date],
) -> Any:
    year, month = _anchor_month(rule)
    interval = int(rule.get("interval", 1))
    if interval < 1:
        raise RuleError("Monthly interval must be positive.")

    release_rule = rule.get("release_rule")
    due_rule = rule.get("due_rule", release_rule)
    if not isinstance(release_rule, dict) or not isinstance(due_rule, dict):
        raise RuleError("Monthly release_rule and due_rule must be objects.")
    end_date = _date(rule["end_date"], "end_date") if rule.get("end_date") else None

    index = 0
    for _ in range(100000):
        current_year, current_month = _month_add(year, month, index * interval)
        release = _monthly_date(
            current_year,
            current_month,
            release_rule,
            workdays,
            holidays,
        )
        due = _monthly_date(
            current_year,
            current_month,
            due_rule,
            workdays,
            holidays,
        )
        if end_date is not None and release > end_date:
            return
        yield f"{current_year:04d}-{current_month:02d}", release, due
        index += 1
    raise RuleError("Monthly schedule exceeded the bounded preview search.")


def validate_rule(rule: dict[str, Any]) -> None:
    if not isinstance(rule, dict):
        raise RuleError("Schedule rule must be an object.")
    frequency = rule.get("frequency")
    if frequency not in {"daily", "weekly", "monthly"}:
        raise RuleError("frequency must be daily, weekly or monthly.")
    _zone(rule.get("timezone"))
    _time(rule.get("release_time", "08:00"), "release_time")
    _time(rule.get("due_time", "17:00"), "due_time")
    _calendar(rule)
    try:
        interval = int(rule.get("interval", 1))
    except (TypeError, ValueError) as exc:
        raise RuleError("interval must be a positive integer.") from exc
    if interval < 1:
        raise RuleError("interval must be a positive integer.")


def generate_preview(
    rule: dict[str, Any],
    *,
    after: date | datetime,
    count: int = 5,
    pauses: list[Any] | None = None,
) -> list[PreviewOccurrence]:
    validate_rule(rule)
    if count < 1 or count > 100:
        raise RuleError("Preview count must be between 1 and 100.")

    zone = _zone(rule["timezone"])
    workdays, holidays = _calendar(rule)
    cutoff = _cutoff(after, zone)
    pause_values = pauses or []
    frequency = rule["frequency"]

    if frequency == "daily":
        candidates = _daily_periods(rule, cutoff)
    elif frequency == "weekly":
        candidates = _weekly_periods(rule)
    else:
        candidates = _monthly_periods(rule, workdays, holidays)

    result: list[PreviewOccurrence] = []
    for period_key, base_release, base_due in candidates:
        if _is_paused(base_release, pause_values):
            continue
        occurrence = _build_occurrence(
            period_key=period_key,
            base_release=base_release,
            base_due=base_due,
            rule=rule,
            zone=zone,
            workdays=workdays,
            holidays=holidays,
        )
        if occurrence.release_at <= cutoff:
            continue
        result.append(occurrence)
        if len(result) == count:
            return result
    return result
