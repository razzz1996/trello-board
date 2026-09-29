from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from boards.models import BoardMembership
from core.clock import now
from django.conf import settings
from workitems.models import Submission, Task

from .jobs import enqueue_job


def _clock(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def next_work_window(value: datetime) -> datetime:
    zone = ZoneInfo(settings.DEPLOYMENT["timezone"])
    local = value.astimezone(zone)
    workdays = set(int(day) for day in settings.DEPLOYMENT["workdays_iso"])
    start = _clock(settings.DEPLOYMENT["workday_start"])
    end = _clock(settings.DEPLOYMENT["workday_end"])

    for offset in range(0, 15):
        candidate_date = local.date() + timedelta(days=offset)
        if candidate_date.isoweekday() not in workdays:
            continue
        if offset == 0:
            if local.time() < start:
                return datetime.combine(candidate_date, start, tzinfo=zone)
            if local.time() < end:
                return value
            continue
        return datetime.combine(candidate_date, start, tzinfo=zone)
    raise RuntimeError("No configured workday found within 14 days.")


def schedule_commitment_notifications(task: Task) -> None:
    commitment = task.current_commitment
    owner_id = task.current_owner_id
    if commitment is None or owner_id is None or task.is_cancelled:
        return

    observed_at = now()
    reminder_minutes = int(settings.DEPLOYMENT["reminder_minutes_before_due"])
    reminder_at = commitment.due_at - timedelta(minutes=reminder_minutes)
    due_warning = reminder_at <= observed_at < commitment.due_at
    common = {
        "task_id": str(task.id),
        "recipient_id": str(owner_id),
        "commitment_id": str(commitment.id),
    }

    enqueue_job(
        semantic_key=f"assignment:{task.id}:{owner_id}:{commitment.id}",
        job_type="assignment_notification",
        run_after=next_work_window(observed_at),
        payload={**common, "due_warning": due_warning},
    )

    reminder_run = next_work_window(reminder_at)
    if reminder_at > observed_at and reminder_run < commitment.due_at:
        enqueue_job(
            semantic_key=f"due-reminder:{task.id}:{owner_id}:{commitment.id}",
            job_type="due_reminder",
            run_after=reminder_run,
            payload=common,
        )

    overdue_run = next_work_window(commitment.due_at)
    enqueue_job(
        semantic_key=f"overdue:{task.id}:{owner_id}:{commitment.id}",
        job_type="overdue_escalation",
        run_after=overdue_run,
        payload=common,
    )

    manager_ids = (
        BoardMembership.objects.filter(
            board=task.board,
            role=BoardMembership.Role.MANAGER,
            is_active=True,
            user__is_active=True,
        )
        .exclude(user_id=owner_id)
        .values_list("user_id", flat=True)
    )
    for manager_id in manager_ids:
        enqueue_job(
            semantic_key=f"overdue-manager:{task.id}:{manager_id}:{commitment.id}",
            job_type="overdue_manager_escalation",
            run_after=overdue_run,
            payload={
                "task_id": str(task.id),
                "recipient_id": str(manager_id),
                "commitment_id": str(commitment.id),
            },
        )


def schedule_review_requests(task: Task, submission: Submission) -> None:
    manager_ids = (
        BoardMembership.objects.filter(
            board=task.board,
            role=BoardMembership.Role.MANAGER,
            is_active=True,
            user__is_active=True,
        )
        .exclude(user_id__in=[submission.accountable_owner_id, submission.submitting_actor_id])
        .values_list("user_id", flat=True)
    )

    run_after = next_work_window(now() + timedelta(seconds=60))
    for manager_id in manager_ids:
        enqueue_job(
            semantic_key=f"review-request:{submission.id}:{manager_id}",
            job_type="review_request",
            run_after=run_after,
            payload={
                "task_id": str(task.id),
                "recipient_id": str(manager_id),
                "submission_id": str(submission.id),
                "commitment_id": str(submission.commitment_id),
            },
        )
