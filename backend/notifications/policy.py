from __future__ import annotations

from typing import Any

from accounts.models import User
from boards.models import BoardColumn, BoardMembership
from core.clock import now
from django.conf import settings
from django.db import transaction
from schedules.models import Schedule
from workitems.models import Task

from .jobs import enqueue_job
from .models import Job, Notification


def _active_work_state(state: str) -> bool:
    return state not in {BoardColumn.State.DONE, BoardColumn.State.REVIEW}


def _eligible_recipient(user: User, task: Task) -> bool:
    return bool(
        user.is_active
        and BoardMembership.objects.filter(
            board=task.board,
            user=user,
            is_active=True,
        ).exists()
    )


def _current_schedule_generation(payload: dict[str, Any], generation: int) -> bool:
    schedule_id = payload.get("schedule_id")
    if not schedule_id:
        return True
    return Schedule.objects.filter(pk=schedule_id, generation=generation, active=True).exists()


def _current_commitment(payload: dict[str, Any], task: Task) -> bool:
    expected = payload.get("commitment_id")
    return expected is None or str(task.current_commitment_id) == str(expected)


def _message(job: Job, task: Task) -> str:
    job_type = job.job_type
    stars = "★" * task.priority
    due = task.current_commitment.due_at.isoformat() if task.current_commitment else "uncommitted"
    if job_type == "assignment_notification":
        prefix = "Assigned, due soon" if job.payload.get("due_warning") else "Assigned"
        return f"{prefix}: {task.title} | {stars} | due {due}"
    if job_type == "due_reminder":
        return f"Due soon: {task.title} | {stars} | due {due}"
    if job_type == "overdue_escalation":
        return f"Overdue: {task.title} | {stars} | due {due}"
    if job_type == "overdue_manager_escalation":
        return f"Overdue escalation: {task.title} | {stars} | due {due}"
    if job_type == "needs_assignment":
        return f"Needs assignment: {task.title} | intended due {task.draft_due_at}"
    if job_type == "review_request":
        return f"Review requested: {task.title} | {stars} | submitted for manager review"
    return f"Task update: {task.title}"


def create_task_notification(job: Job) -> Notification | None:
    payload = dict(job.payload)
    task_id = payload.get("task_id")
    recipient_id = payload.get("recipient_id")
    if not task_id or not recipient_id:
        return None

    task = (
        Task.objects.select_related("board", "column", "current_commitment")
        .filter(pk=task_id)
        .first()
    )
    user = User.objects.filter(pk=recipient_id).first()
    if task is None or user is None or not _eligible_recipient(user, task):
        return None
    if not _current_schedule_generation(payload, job.generation):
        return None
    if not _current_commitment(payload, task):
        return None

    if job.job_type in {
        "needs_assignment",
        "review_request",
        "overdue_manager_escalation",
    }:
        membership = BoardMembership.objects.filter(
            board=task.board,
            user=user,
            role=BoardMembership.Role.MANAGER,
            is_active=True,
        ).first()
        if membership is None:
            return None
        if job.job_type == "needs_assignment":
            if task.current_owner_id is not None or task.committed_at is not None:
                return None
        elif job.job_type == "review_request":
            submission_id = payload.get("submission_id")
            if not isinstance(submission_id, str) or not submission_id:
                return None
            submission = task.submissions.filter(pk=submission_id, is_current=True).first()
            if submission is None or hasattr(submission, "review"):
                return None
        else:
            if task.is_cancelled or not _active_work_state(task.column.state):
                return None
            if task.current_commitment is None or task.current_commitment.due_at > now():
                return None
    else:
        if task.is_cancelled or task.current_owner_id != user.id:
            return None
        if job.job_type == "assignment_notification":
            if task.committed_at is None or task.column.state == BoardColumn.State.DONE:
                return None
        elif job.job_type == "due_reminder":
            if not _active_work_state(task.column.state):
                return None
            if task.current_commitment is None or task.current_commitment.due_at <= now():
                return None
        elif job.job_type == "overdue_escalation":
            if not _active_work_state(task.column.state):
                return None
            if task.current_commitment is None or task.current_commitment.due_at > now():
                return None

    observed_at = now()
    with transaction.atomic():
        notification, _ = Notification.objects.get_or_create(
            semantic_key=job.semantic_key,
            defaults={
                "recipient": user,
                "task": task,
                "kind": job.job_type,
                "scheduled_for": job.run_after,
                "observed_at": observed_at,
                "status": Notification.Status.QUEUED,
                "destination_generation": user.slack_destination_generation,
                "message_preview": _message(job, task)[:3000],
            },
        )
        slack_mode = settings.DEPLOYMENT["slack_mode"]
        if slack_mode in {"dry_run", "live"}:
            enqueue_job(
                semantic_key=f"slack:{notification.id}:{notification.destination_generation}",
                job_type="slack_delivery",
                run_after=observed_at,
                payload={"notification_id": str(notification.id)},
                generation=notification.destination_generation,
            )
    return notification
