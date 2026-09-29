from __future__ import annotations

import logging
import os

from core.clock import now
from django.conf import settings
from django.db import DatabaseError
from schedules.generation import generate_schedule_batch

from . import jobs
from .digest import create_personal_digest
from .models import Job, WorkerHeartbeat
from .policy import create_task_notification
from .slack import deliver

logger = logging.getLogger("productivity.worker")

TASK_NOTIFICATION_TYPES = {
    "assignment_notification",
    "due_reminder",
    "overdue_escalation",
    "overdue_manager_escalation",
    "needs_assignment",
    "review_request",
}


def process_lease(lease: jobs.Lease) -> None:
    job = Job.objects.filter(pk=lease.job_id, lease_token=lease.token).first()
    if job is None:
        raise jobs.LeaseError("Claimed job disappeared or lease token changed.")

    if job.job_type == "recurrence_scan":
        schedule_id = job.payload.get("schedule_id")
        if not schedule_id:
            jobs.fail_permanent(job.id, lease.token, code="schedule_id_missing")
            return
        generate_schedule_batch(schedule_id, limit=100)
        jobs.succeed(job.id, lease.token)
        return

    if job.job_type in TASK_NOTIFICATION_TYPES:
        notification = create_task_notification(job)
        if notification is None:
            jobs.suppress(job.id, lease.token, code="stale_notification")
        else:
            jobs.succeed(job.id, lease.token)
        return

    if job.job_type == "personal_digest":
        notification = create_personal_digest(job)
        if notification is None:
            jobs.suppress(job.id, lease.token, code="recipient_unavailable")
        else:
            jobs.succeed(job.id, lease.token)
        return

    if job.job_type == "slack_delivery":
        deliver(job, lease.token)
        return

    if job.job_type == "manager_report":
        from reports.services import create_scheduled_manager_report

        snapshot = create_scheduled_manager_report(job)
        if snapshot is None:
            jobs.suppress(job.id, lease.token, code="report_scope_empty_or_revoked")
        else:
            jobs.succeed(job.id, lease.token)
        return

    jobs.fail_permanent(job.id, lease.token, code="unknown_job_type")


def worker_tick() -> dict[str, int]:
    jobs.recover_expired_leases()
    lease_seconds = int(settings.DEPLOYMENT["lease_seconds"])
    claimed = jobs.claim_jobs(limit=20, lease_seconds=lease_seconds)
    succeeded = 0
    failed = 0
    for lease in claimed:
        try:
            process_lease(lease)
            succeeded += 1
        except jobs.LeaseError:
            failed += 1
            logger.exception(
                "Lease fencing rejected worker completion.",
                extra={"job_id": lease.job_id, "error_code": "stale_lease"},
            )
        except DatabaseError:
            failed += 1
            try:
                jobs.fail_retryable(
                    lease.job_id,
                    lease.token,
                    code="database_error",
                    delay_seconds=60,
                )
            except jobs.LeaseError:
                pass
            logger.exception(
                "Database error while processing job.",
                extra={"job_id": lease.job_id, "error_code": "database_error"},
            )
        except Exception:
            failed += 1
            try:
                row = Job.objects.filter(pk=lease.job_id).only("attempts").first()
                if row is not None and row.attempts < 5:
                    jobs.fail_retryable(
                        lease.job_id,
                        lease.token,
                        code="unexpected_worker_error",
                        delay_seconds=min(60 * (2 ** max(row.attempts - 1, 0)), 960),
                    )
                else:
                    jobs.fail_permanent(
                        lease.job_id,
                        lease.token,
                        code="unexpected_worker_error",
                    )
            except jobs.LeaseError:
                pass
            logger.exception(
                "Unexpected worker error.",
                extra={"job_id": lease.job_id, "error_code": "unexpected_worker_error"},
            )

    WorkerHeartbeat.objects.update_or_create(
        name="worker",
        defaults={
            "last_seen_at": now(),
            "process_id": os.getpid(),
            "details": {"claimed": len(claimed), "processed": succeeded, "failed": failed},
        },
    )
    return {"claimed": len(claimed), "processed": succeeded, "failed": failed}
