from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from boards.models import Board, BoardColumn
from core.clock import now
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .errors import DomainError
from .models import AuditEvent, Task

TEMP_POSITION = 2_100_000


def configure_recurrence(
    task: Task,
    *,
    frequency: str,
    next_at: datetime | None,
) -> None:
    if not isinstance(frequency, str):
        raise DomainError(
            "invalid_recurrence",
            "Repeat must be none, daily, weekly, or monthly.",
            field_errors={"recurrence_frequency": ["Invalid repeat option."]},
        )
    normalized = frequency.strip().upper()
    if normalized not in Task.Recurrence.values:
        raise DomainError(
            "invalid_recurrence",
            "Repeat must be none, daily, weekly, or monthly.",
            field_errors={"recurrence_frequency": ["Invalid repeat option."]},
        )
    if normalized == Task.Recurrence.NONE:
        task.recurrence_frequency = Task.Recurrence.NONE
        task.recurrence_next_at = None
        task.recurrence_anchor_day = None
        task.recurrence_generation += 1
        return

    if next_at is None or timezone.is_naive(next_at):
        raise DomainError(
            "recurrence_date_required",
            "A timezone-aware next action date is required for repeating cards.",
            field_errors={"recurrence_next_at": ["Required."]},
        )
    if next_at <= now():
        raise DomainError(
            "recurrence_date_in_past",
            "The next action date must be in the future.",
            field_errors={"recurrence_next_at": ["Choose a future date and time."]},
        )

    zone = ZoneInfo(settings.DEPLOYMENT["timezone"])
    task.recurrence_frequency = normalized
    task.recurrence_next_at = next_at
    task.recurrence_anchor_day = next_at.astimezone(zone).day
    task.recurrence_generation += 1


def _advance(value: datetime, frequency: str, anchor_day: int | None) -> datetime:
    if timezone.is_naive(value):
        raise ValueError("Recurring action time must be timezone-aware.")

    zone = ZoneInfo(settings.DEPLOYMENT["timezone"])
    original_zone = value.tzinfo
    local = value.astimezone(zone)

    if frequency == Task.Recurrence.DAILY:
        advanced = local + timedelta(days=1)
    elif frequency == Task.Recurrence.WEEKLY:
        advanced = local + timedelta(days=7)
    elif frequency == Task.Recurrence.MONTHLY:
        month = local.month + 1
        year = local.year
        if month == 13:
            month = 1
            year += 1
        desired_day = anchor_day or local.day
        day = min(desired_day, monthrange(year, month)[1])
        advanced = local.replace(year=year, month=month, day=day)
    else:
        raise ValueError(f"Unsupported recurrence frequency: {frequency}")

    return advanced.astimezone(original_zone)


def _move_to_inbox(task: Task, inbox: BoardColumn) -> None:
    source_id = task.column_id
    target_items = list(
        Task.objects.select_for_update()
        .filter(column=inbox, is_cancelled=False, is_archived=False)
        .exclude(pk=task.pk)
        .order_by("position", "id")
    )
    source_items = list(
        Task.objects.select_for_update()
        .filter(column_id=source_id, is_cancelled=False, is_archived=False)
        .exclude(pk=task.pk)
        .order_by("position", "id")
    )

    Task.objects.filter(pk=task.pk).update(position=TEMP_POSITION)
    if source_id != inbox.id:
        for position, item in enumerate(source_items):
            if item.position != position:
                Task.objects.filter(pk=item.pk).update(position=position)

    target_items.append(task)
    for position, item in enumerate(target_items):
        Task.objects.filter(pk=item.pk).update(column=inbox, position=position)

    task.column = inbox
    task.position = len(target_items) - 1


def trigger_recurrence(
    *,
    task_id,
    generation: int,
    observed_at: datetime | None = None,
) -> bool:
    observed_at = observed_at or now()
    with transaction.atomic():
        board_id = Task.objects.filter(pk=task_id).values_list("board_id", flat=True).first()
        if board_id is None:
            return False
        board = Board.objects.select_for_update().get(pk=board_id)
        task = (
            Task.objects.select_for_update(of=("self",))
            .select_related("board", "column", "current_commitment")
            .filter(pk=task_id, board=board)
            .first()
        )
        if task is None:
            return False
        if (
            board.archived
            or task.is_cancelled
            or task.is_archived
            or task.column.is_archived
            or task.recurrence_frequency == Task.Recurrence.NONE
            or task.recurrence_next_at is None
            or task.recurrence_generation != generation
            or task.recurrence_next_at > observed_at
        ):
            return False

        scheduled_for = task.recurrence_next_at
        next_at = scheduled_for
        while next_at <= observed_at:
            next_at = _advance(
                next_at,
                task.recurrence_frequency,
                task.recurrence_anchor_day,
            )

        inbox = BoardColumn.objects.get(
            board=board,
            state=BoardColumn.State.BACKLOG,
        )
        before = {
            "column_state": task.column.state,
            "recurrence_next_at": scheduled_for.isoformat(),
            "recurrence_generation": task.recurrence_generation,
        }
        _move_to_inbox(task, inbox)
        task.checklist_items.update(checked=False)
        task.submissions.filter(is_current=True).update(is_current=False)

        task.current_commitment = None
        task.committed_at = None
        task.original_owner = None
        task.draft_due_at = None
        task.recurrence_last_triggered_at = observed_at
        task.recurrence_next_at = next_at
        task.recurrence_generation += 1
        task.row_version += 1
        board.revision += 1

        task.save(
            update_fields=[
                "column",
                "position",
                "current_commitment",
                "committed_at",
                "original_owner",
                "draft_due_at",
                "recurrence_last_triggered_at",
                "recurrence_next_at",
                "recurrence_generation",
                "row_version",
                "updated_at",
            ]
        )
        board.save(update_fields=["revision", "updated_at"])
        AuditEvent.objects.create(
            board=board,
            board_revision=board.revision,
            task=task,
            actor=task.created_by,
            action="recurrence_return_to_inbox",
            reason="Recurring card became actionable again.",
            before=before,
            after={
                "column_state": BoardColumn.State.BACKLOG,
                "recurrence_next_at": next_at.isoformat(),
                "recurrence_generation": task.recurrence_generation,
            },
        )
        return True
