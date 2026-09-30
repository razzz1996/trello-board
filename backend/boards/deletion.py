from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from notifications.models import Job
from schedules.models import Occurrence, Schedule, SchedulePause, ScheduleRevision
from workitems.deletion import purge_task_dependencies
from workitems.models import AuditEvent, Task

from .models import Board
from .permissions import require_site_admin

logger = logging.getLogger("productivity.boards")


class BoardDeletionError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def delete_board(*, actor, board_id, confirm_name: str) -> dict[str, Any]:
    require_site_admin(actor)
    with transaction.atomic():
        board = Board.objects.select_for_update().filter(pk=board_id).first()
        if board is None:
            raise BoardDeletionError("not_found", "Board not found.", 404)
        if confirm_name.strip() != board.name:
            raise BoardDeletionError(
                "confirmation_mismatch",
                "Type the exact board name to confirm permanent deletion.",
                400,
            )

        task_ids = list(Task.objects.filter(board=board).values_list("id", flat=True))
        schedule_ids = list(Schedule.objects.filter(board=board).values_list("id", flat=True))
        for schedule_id in schedule_ids:
            Job.objects.filter(payload__schedule_id=str(schedule_id)).delete()
        Occurrence.objects.filter(schedule_id__in=schedule_ids).delete()

        purge_task_dependencies(task_ids)

        SchedulePause.objects.filter(schedule_id__in=schedule_ids).delete()
        Schedule.objects.filter(id__in=schedule_ids).update(current_revision=None)
        ScheduleRevision.objects.filter(schedule_id__in=schedule_ids).delete()
        Schedule.objects.filter(id__in=schedule_ids).delete()

        AuditEvent.objects.filter(board=board).delete()
        summary = {
            "deleted": True,
            "board_id": str(board.id),
            "board_name": board.name,
            "task_count": len(task_ids),
            "schedule_count": len(schedule_ids),
        }
        board.delete()

    logger.info(
        "Board permanently deleted.",
        extra={
            "actor_id": str(actor.id),
            "board_id": summary["board_id"],
            "task_count": summary["task_count"],
            "schedule_count": summary["schedule_count"],
        },
    )
    return summary
