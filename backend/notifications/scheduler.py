from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from accounts.models import User
from core.clock import now
from django.conf import settings
from schedules.models import Schedule

from .jobs import enqueue_job
from .models import WorkerHeartbeat


def _local_time(value: str):
    return datetime.strptime(value, "%H:%M").time()


def scheduler_tick() -> dict[str, int]:
    observed_at = now()
    zone = ZoneInfo(settings.DEPLOYMENT["timezone"])
    local = observed_at.astimezone(zone)
    minute_key = local.strftime("%Y%m%d%H%M")

    recurrence_count = 0
    for schedule in Schedule.objects.filter(active=True, board__archived=False).only(
        "id", "generation", "cursor_period_key"
    ):
        enqueue_job(
            semantic_key=f"recurrence-scan:{schedule.id}:{schedule.generation}:{minute_key}",
            job_type="recurrence_scan",
            run_after=observed_at,
            payload={"schedule_id": str(schedule.id)},
            generation=schedule.generation,
        )
        recurrence_count += 1

    digest_count = 0
    workdays = set(settings.DEPLOYMENT["workdays_iso"])
    if local.isoweekday() in workdays and local.time() >= _local_time(
        settings.DEPLOYMENT["member_digest_time"]
    ):
        user_ids = (
            User.objects.filter(
                is_active=True,
                board_memberships__is_active=True,
                board_memberships__board__archived=False,
            )
            .values_list("id", flat=True)
            .distinct()
        )
        for user_id in user_ids:
            enqueue_job(
                semantic_key=f"member-digest:{user_id}:{local.date().isoformat()}",
                job_type="personal_digest",
                run_after=observed_at,
                payload={"recipient_id": str(user_id), "report_date": local.date().isoformat()},
            )
            digest_count += 1

    manager_count = 0
    manager_id = settings.DEPLOYMENT.get("manager_user_id")
    if (
        manager_id
        and local.isoweekday() in workdays
        and local.time() >= _local_time(settings.DEPLOYMENT["manager_report_time"])
        and User.objects.filter(pk=manager_id, is_active=True).exists()
    ):
        enqueue_job(
            semantic_key=f"manager-report:{manager_id}:{local.date().isoformat()}:v1",
            job_type="manager_report",
            run_after=observed_at,
            payload={"recipient_id": str(manager_id), "report_date": local.date().isoformat()},
        )
        manager_count = 1

    WorkerHeartbeat.objects.update_or_create(
        name="scheduler",
        defaults={
            "last_seen_at": observed_at,
            "details": {
                "recurrence_enqueued": recurrence_count,
                "digest_enqueued": digest_count,
                "manager_report_enqueued": manager_count,
            },
        },
    )
    return {
        "recurrence_enqueued": recurrence_count,
        "digest_enqueued": digest_count,
        "manager_report_enqueued": manager_count,
    }
