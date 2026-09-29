from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from boards.models import Board, BoardMembership
from boards.permissions import require_board_manager, require_board_member
from core.clock import now
from django.db import transaction
from workitems.models import AuditEvent

from .engine import RuleError, generate_preview, validate_rule
from .models import Schedule, SchedulePause, ScheduleRevision


class ScheduleError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def serialize_schedule(schedule: Schedule) -> dict[str, Any]:
    revision = schedule.current_revision
    return {
        "id": str(schedule.id),
        "board_id": str(schedule.board_id),
        "name": schedule.name,
        "timezone": schedule.timezone,
        "active": schedule.active,
        "generation": schedule.generation,
        "cursor_period_key": schedule.cursor_period_key,
        "current_revision": None
        if revision is None
        else {
            "id": str(revision.id),
            "revision": revision.revision,
            "rule": revision.rule,
            "template_fields": revision.template_fields,
            "effective_base_period": revision.effective_base_period,
            "reason": revision.reason,
            "published_at": revision.published_at.isoformat(),
        },
        "paused": schedule.pauses.filter(end_base_date__isnull=True).exists(),
    }


def _schedule_for_update(schedule_id) -> Schedule:
    try:
        return (
            Schedule.objects.select_for_update()
            .select_related("board", "current_revision")
            .get(pk=schedule_id)
        )
    except Schedule.DoesNotExist as exc:
        raise ScheduleError("not_found", "Schedule not found.", 404) from exc


def _audit(schedule: Schedule, actor, action: str, reason: str, after: dict[str, Any]) -> None:
    schedule.board.revision += 1
    schedule.board.save(update_fields=["revision", "updated_at"])
    AuditEvent.objects.create(
        board=schedule.board,
        board_revision=schedule.board.revision,
        task=None,
        actor=actor,
        action=action,
        reason=reason,
        before={},
        after=after,
    )


def _validate_template(board: Board, template: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(template, dict):
        raise ScheduleError("invalid_template", "template_fields must be an object.")
    title = str(template.get("title", "")).strip()
    if not title or len(title) > 200:
        raise ScheduleError(
            "invalid_template", "Template title is required and must be <= 200 characters."
        )
    priority = template.get("priority", 1)
    try:
        priority = int(priority)
    except (TypeError, ValueError) as exc:
        raise ScheduleError("invalid_template", "Template priority must be 1, 2, or 3.") from exc
    if priority not in {1, 2, 3}:
        raise ScheduleError("invalid_template", "Template priority must be 1, 2, or 3.")
    owner_id = template.get("owner_id")
    if owner_id is None:
        raise ScheduleError("invalid_template", "Template owner_id is required.")
    membership = BoardMembership.objects.filter(
        board=board,
        user_id=owner_id,
        is_active=True,
        user__is_active=True,
    ).first()
    if membership is None:
        raise ScheduleError("invalid_template", "Template owner must be an active board member.")
    criteria = str(template.get("acceptance_criteria", "")).strip()
    if not criteria or len(criteria) > 10000:
        raise ScheduleError("invalid_template", "Template acceptance criteria are required.")
    required_checklist = template.get("required_checklist", [])
    if not isinstance(required_checklist, list):
        raise ScheduleError("invalid_template", "required_checklist must be a list.")
    cleaned_checklist: list[str] = []
    for item in required_checklist:
        text = str(item).strip()
        if not text or len(text) > 500:
            raise ScheduleError(
                "invalid_template", "Checklist entries must be 1 to 500 characters."
            )
        cleaned_checklist.append(text)
    return {
        "title": title,
        "description": str(template.get("description", ""))[:20000],
        "priority": priority,
        "owner_id": str(owner_id),
        "acceptance_criteria": criteria,
        "required_checklist": cleaned_checklist,
    }


def create_draft(*, actor, board_id, name: str, timezone_name: str) -> Schedule:
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 200:
        raise ScheduleError("invalid_name", "Schedule name is required.")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleError("invalid_timezone", "timezone must be a valid IANA zone.") from exc
    with transaction.atomic():
        board = Board.objects.select_for_update().get(pk=board_id, archived=False)
        require_board_member(actor, board.id, for_update=True)
        schedule = Schedule.objects.create(
            board=board,
            name=clean_name,
            timezone=timezone_name,
            active=False,
            created_by=actor,
        )
        _audit(schedule, actor, "create_schedule_draft", "", serialize_schedule(schedule))
        return schedule


def preview_rule(
    *, actor, board_id, rule: dict[str, Any], after: date, pauses: list[Any] | None = None
) -> list[dict[str, Any]]:
    require_board_member(actor, board_id)
    try:
        validate_rule(rule)
        return [
            item.as_dict() for item in generate_preview(rule, after=after, count=5, pauses=pauses)
        ]
    except RuleError as exc:
        raise ScheduleError("invalid_rule", str(exc)) from exc


def _validate_frequency_boundary(old_rule: dict[str, Any], new_rule: dict[str, Any]) -> None:
    identity_keys = ("frequency", "anchor_date", "anchor_month")
    if any(old_rule.get(key) != new_rule.get(key) for key in identity_keys):
        raise ScheduleError(
            "new_schedule_required",
            "Changing frequency or anchor requires a new schedule with an explicit boundary.",
            409,
        )


def _validate_effective_period(
    *,
    frequency: str,
    value: str,
    cursor: str,
    previous: str | None = None,
) -> str:
    clean = value.strip()
    try:
        if frequency == "daily":
            parsed = date.fromisoformat(clean)
            canonical = parsed.isoformat()
        elif frequency == "weekly":
            parsed = datetime.strptime(f"{clean}-1", "%G-W%V-%u").date()
            iso_year, iso_week, _ = parsed.isocalendar()
            canonical = f"{iso_year:04d}-W{iso_week:02d}"
        elif frequency == "monthly":
            parsed = date.fromisoformat(f"{clean}-01")
            canonical = f"{parsed.year:04d}-{parsed.month:02d}"
        else:
            raise ValueError("unsupported frequency")
    except ValueError as exc:
        raise ScheduleError(
            "invalid_effective_period",
            "effective_base_period does not match the recurrence frequency.",
        ) from exc
    if clean != canonical:
        raise ScheduleError(
            "invalid_effective_period",
            f"effective_base_period must use canonical {frequency} period format.",
        )
    if cursor and clean <= cursor:
        raise ScheduleError(
            "issued_period_boundary",
            "A schedule revision must start after the last issued recurrence period.",
            409,
        )
    if previous is not None and clean <= previous:
        raise ScheduleError(
            "overlapping_revision",
            "A schedule revision must start after the prior revision boundary.",
            409,
        )
    return clean


def publish(
    *,
    actor,
    schedule_id,
    rule: dict[str, Any],
    template_fields: dict[str, Any],
    effective_base_period: str,
    reason: str,
) -> Schedule:
    clean_reason = reason.strip()
    if not clean_reason:
        raise ScheduleError("reason_required", "Publishing a schedule requires a reason.")
    with transaction.atomic():
        schedule = _schedule_for_update(schedule_id)
        require_board_manager(actor, schedule.board_id, for_update=True)
        if schedule.current_revision_id is not None:
            raise ScheduleError(
                "already_published", "Use revise for an existing published schedule.", 409
            )
        template = _validate_template(schedule.board, template_fields)
        effective_period = _validate_effective_period(
            frequency=str(rule.get("frequency", "")),
            value=effective_base_period,
            cursor=schedule.cursor_period_key,
        )
        try:
            validate_rule(rule)
            local_date = now().astimezone(ZoneInfo(str(rule["timezone"]))).date()
            generate_preview(rule, after=local_date, count=5)
        except RuleError as exc:
            raise ScheduleError("invalid_rule", str(exc)) from exc
        revision = ScheduleRevision.objects.create(
            schedule=schedule,
            revision=1,
            rule=rule,
            template_fields=template,
            effective_base_period=effective_period,
            actor=actor,
            reason=clean_reason,
        )
        schedule.current_revision = revision
        schedule.active = True
        schedule.generation += 1
        schedule.timezone = str(rule["timezone"])
        schedule.save(update_fields=["current_revision", "active", "generation", "timezone"])
        _audit(schedule, actor, "publish_schedule", clean_reason, serialize_schedule(schedule))
        return schedule


def revise(
    *,
    actor,
    schedule_id,
    rule: dict[str, Any],
    template_fields: dict[str, Any],
    effective_base_period: str,
    reason: str,
) -> Schedule:
    clean_reason = reason.strip()
    if not clean_reason:
        raise ScheduleError("reason_required", "Schedule revision requires a reason.")
    with transaction.atomic():
        schedule = _schedule_for_update(schedule_id)
        require_board_manager(actor, schedule.board_id, for_update=True)
        current = schedule.current_revision
        if current is None:
            raise ScheduleError("not_published", "Publish the schedule before revising it.", 409)
        _validate_frequency_boundary(current.rule, rule)
        template = _validate_template(schedule.board, template_fields)
        effective_period = _validate_effective_period(
            frequency=str(rule.get("frequency", "")),
            value=effective_base_period,
            cursor=schedule.cursor_period_key,
            previous=current.effective_base_period,
        )
        try:
            validate_rule(rule)
            local_date = now().astimezone(ZoneInfo(str(rule["timezone"]))).date()
            generate_preview(rule, after=local_date, count=5)
        except RuleError as exc:
            raise ScheduleError("invalid_rule", str(exc)) from exc
        revision = ScheduleRevision.objects.create(
            schedule=schedule,
            revision=current.revision + 1,
            rule=rule,
            template_fields=template,
            effective_base_period=effective_period,
            actor=actor,
            reason=clean_reason,
        )
        schedule.current_revision = revision
        schedule.generation += 1
        schedule.timezone = str(rule["timezone"])
        schedule.save(update_fields=["current_revision", "generation", "timezone"])
        _audit(schedule, actor, "revise_schedule", clean_reason, serialize_schedule(schedule))
        return schedule


def pause(*, actor, schedule_id, start_base_date: date, reason: str) -> Schedule:
    clean_reason = reason.strip()
    if not clean_reason:
        raise ScheduleError("reason_required", "Pausing a schedule requires a reason.")
    with transaction.atomic():
        schedule = _schedule_for_update(schedule_id)
        require_board_manager(actor, schedule.board_id, for_update=True)
        if not schedule.active:
            raise ScheduleError("inactive_schedule", "Only active schedules can be paused.", 409)
        if (
            SchedulePause.objects.select_for_update()
            .filter(schedule=schedule, end_base_date__isnull=True)
            .exists()
        ):
            raise ScheduleError("already_paused", "Schedule already has an open pause.", 409)
        SchedulePause.objects.create(
            schedule=schedule,
            start_base_date=start_base_date,
            end_base_date=None,
            actor=actor,
            reason=clean_reason,
        )
        schedule.generation += 1
        schedule.save(update_fields=["generation"])
        _audit(schedule, actor, "pause_schedule", clean_reason, serialize_schedule(schedule))
        return schedule


def resume(*, actor, schedule_id, end_base_date: date, reason: str) -> Schedule:
    clean_reason = reason.strip()
    if not clean_reason:
        raise ScheduleError("reason_required", "Resuming a schedule requires a reason.")
    with transaction.atomic():
        schedule = _schedule_for_update(schedule_id)
        require_board_manager(actor, schedule.board_id, for_update=True)
        pause_row = (
            SchedulePause.objects.select_for_update()
            .filter(schedule=schedule, end_base_date__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if pause_row is None:
            raise ScheduleError("not_paused", "Schedule has no open pause.", 409)
        if end_base_date <= pause_row.start_base_date:
            raise ScheduleError("invalid_pause", "Resume base date must be after pause start.")
        pause_row.end_base_date = end_base_date
        pause_row.save(update_fields=["end_base_date"])
        schedule.generation += 1
        schedule.save(update_fields=["generation"])
        _audit(schedule, actor, "resume_schedule", clean_reason, serialize_schedule(schedule))
        return schedule
