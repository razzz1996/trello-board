from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from boards.models import Board
from boards.permissions import require_board_member
from django.db import transaction
from notifications.models import Job, Notification
from schedules.models import Occurrence

from .errors import DomainError
from .models import (
    AuditEvent,
    ChangeProposal,
    ChecklistItem,
    Comment,
    CommitmentRevision,
    Review,
    Submission,
    Task,
)


def _task_ids(values: Iterable[Any]) -> list[Any]:
    return list(values)


def purge_task_dependencies(task_ids: Iterable[Any]) -> int:
    ids = _task_ids(task_ids)
    if not ids:
        return 0

    notification_ids = list(
        Notification.objects.filter(task_id__in=ids).values_list("id", flat=True)
    )
    for task_id in ids:
        Job.objects.filter(payload__task_id=str(task_id)).delete()
    for notification_id in notification_ids:
        Job.objects.filter(payload__notification_id=str(notification_id)).delete()
    Notification.objects.filter(id__in=notification_ids).delete()
    Occurrence.objects.filter(task_id__in=ids).delete()
    Review.objects.filter(submission__task_id__in=ids).delete()
    Submission.objects.filter(task_id__in=ids).delete()
    ChangeProposal.objects.filter(task_id__in=ids).delete()
    Comment.objects.filter(task_id__in=ids).delete()
    ChecklistItem.objects.filter(task_id__in=ids).delete()
    AuditEvent.objects.filter(task_id__in=ids).delete()

    Task.objects.filter(id__in=ids).update(current_commitment=None)
    CommitmentRevision.objects.filter(task_id__in=ids).delete()
    deleted, _ = Task.objects.filter(id__in=ids).delete()
    return deleted


def delete_task(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
) -> dict[str, Any]:
    with transaction.atomic():
        board_id = (
            Task.objects.filter(
                pk=task_id,
                is_archived=False,
                column__is_archived=False,
            )
            .values_list("board_id", flat=True)
            .first()
        )
        if board_id is None:
            raise DomainError("not_found", "Card not found.", status=404)

        board = Board.objects.select_for_update().get(pk=board_id)
        require_board_member(actor, board.id, for_update=True)
        task = (
            Task.objects.select_for_update().select_related("column").get(pk=task_id, board=board)
        )
        if task.row_version != expected_version or board.revision != expected_board_revision:
            raise DomainError(
                "stale_state",
                "The card or board changed since it was loaded.",
                status=409,
            )
        column_id = task.column_id
        before = {
            "task_id": str(task.id),
            "title": task.title,
            "column_state": task.column.state,
            "row_version": task.row_version,
            "recurrence_frequency": task.recurrence_frequency,
            "recurrence_next_at": (
                task.recurrence_next_at.isoformat() if task.recurrence_next_at else None
            ),
        }

        purge_task_dependencies([task.id])
        remaining = list(
            Task.objects.select_for_update()
            .filter(column_id=column_id, is_cancelled=False, is_archived=False)
            .order_by("position", "id")
        )
        for position, item in enumerate(remaining):
            if item.position != position:
                Task.objects.filter(pk=item.pk).update(position=position)

        board.revision += 1
        board.save(update_fields=["revision", "updated_at"])
        AuditEvent.objects.create(
            board=board,
            board_revision=board.revision,
            task=None,
            actor=actor,
            action="delete_task",
            reason="Card deleted by a board user.",
            before=before,
            after={"deleted": True},
        )
        return {
            "deleted": True,
            "task_id": str(task_id),
            "board_id": str(board.id),
            "board_revision": board.revision,
        }
