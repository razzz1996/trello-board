from __future__ import annotations

from zoneinfo import ZoneInfo

from accounts.models import User
from boards.models import BoardColumn
from core.clock import now
from django.conf import settings
from workitems.models import Task

from .jobs import enqueue_job
from .models import Job, Notification


def create_personal_digest(job: Job) -> Notification | None:
    recipient_id = job.payload.get("recipient_id")
    user = User.objects.filter(pk=recipient_id, is_active=True).first()
    if user is None:
        return None

    observed_at = now()
    zone = ZoneInfo(settings.DEPLOYMENT["timezone"])
    local_date = observed_at.astimezone(zone).date()
    tasks = (
        Task.objects.filter(
            current_owner=user,
            is_cancelled=False,
            is_archived=False,
            column__is_archived=False,
            board__memberships__user=user,
            board__memberships__is_active=True,
        )
        .select_related("board", "column", "current_commitment")
        .distinct()
    )
    active = tasks.exclude(column__state=BoardColumn.State.DONE)
    overdue = [
        task
        for task in active
        if task.current_commitment
        and task.current_commitment.due_at < observed_at
    ]
    due_today = [
        task
        for task in active
        if task.current_commitment
        and task.current_commitment.due_at.astimezone(zone).date() == local_date
    ]
    priority = list(active.filter(priority=3)[:20])
    review = list(
        active.filter(
            submissions__is_current=True,
            submissions__review__isnull=True,
        ).distinct()[:20]
    )

    lines = [
        f"Daily task digest for {local_date.isoformat()}",
        f"Due today: {len(due_today)}",
        f"Overdue: {len(overdue)}",
        f"★★★ active: {len(priority)}",
        f"Waiting review: {len(review)}",
    ]
    if due_today:
        lines.append("Due today:")
        lines.extend(f"- {item.title}" for item in due_today[:15])
    if overdue:
        lines.append("Overdue:")
        lines.extend(f"- {item.title}" for item in overdue[:15])

    notification, _ = Notification.objects.get_or_create(
        semantic_key=job.semantic_key,
        defaults={
            "recipient": user,
            "task": None,
            "kind": "personal_digest",
            "scheduled_for": job.run_after,
            "observed_at": observed_at,
            "status": Notification.Status.QUEUED,
            "destination_generation": user.slack_destination_generation,
            "message_preview": "\n".join(lines)[:3000],
        },
    )
    if settings.DEPLOYMENT["slack_mode"] in {"dry_run", "live"}:
        enqueue_job(
            semantic_key=f"slack:{notification.id}:{notification.destination_generation}",
            job_type="slack_delivery",
            run_after=observed_at,
            payload={"notification_id": str(notification.id)},
            generation=notification.destination_generation,
        )
    return notification
