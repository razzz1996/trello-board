from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from core.clock import now
from django.db import transaction
from django.db.models import Q

from .models import Job


class LeaseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Lease:
    job_id: uuid.UUID
    token: uuid.UUID
    job_type: str
    payload: dict[str, Any]
    generation: int


def enqueue_job(
    *,
    semantic_key: str,
    job_type: str,
    run_after,
    payload: dict[str, Any],
    generation: int = 1,
) -> Job:
    job, _ = Job.objects.get_or_create(
        semantic_key=semantic_key,
        defaults={
            "job_type": job_type,
            "run_after": run_after,
            "payload": payload,
            "generation": generation,
            "status": Job.Status.READY,
        },
    )
    return job


def recover_expired_leases() -> dict[str, int]:
    observed_at = now()
    with transaction.atomic():
        ambiguous = Job.objects.select_for_update().filter(
            status=Job.Status.SENDING,
            lease_expires_at__lt=observed_at,
        )
        unknown_count = ambiguous.update(
            status=Job.Status.UNKNOWN,
            lease_token=None,
            lease_expires_at=None,
            last_error_code="expired_sending_lease",
        )
        internal = Job.objects.select_for_update().filter(
            status=Job.Status.LEASED,
            lease_expires_at__lt=observed_at,
        )

        retry_count = internal.update(
            status=Job.Status.READY,
            lease_token=None,
            lease_expires_at=None,
            last_error_code="expired_internal_lease",
        )
    return {"unknown": unknown_count, "requeued": retry_count}


def claim_jobs(*, limit: int = 10, lease_seconds: int = 120) -> list[Lease]:
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    if lease_seconds < 30:
        raise ValueError("lease_seconds must be at least 30")

    observed_at = now()
    leases: list[Lease] = []
    with transaction.atomic():
        rows = list(
            Job.objects.select_for_update(skip_locked=True)
            .filter(
                Q(status=Job.Status.READY)
                | Q(status=Job.Status.RETRY_WAIT, run_after__lte=observed_at),
                run_after__lte=observed_at,
            )
            .order_by("run_after", "id")[:limit]
        )
        for row in rows:
            token = uuid.uuid4()

            row.status = Job.Status.LEASED
            row.lease_token = token
            row.lease_expires_at = observed_at + timedelta(seconds=lease_seconds)
            row.attempts += 1
            row.save(
                update_fields=[
                    "status",
                    "lease_token",
                    "lease_expires_at",
                    "attempts",
                    "updated_at",
                ]
            )
            leases.append(
                Lease(
                    job_id=row.id,
                    token=token,
                    job_type=row.job_type,
                    payload=dict(row.payload),
                    generation=row.generation,
                )
            )
    return leases


def heartbeat(job_id: uuid.UUID, token: uuid.UUID, *, lease_seconds: int = 120) -> None:
    observed_at = now()
    updated = Job.objects.filter(
        pk=job_id,
        lease_token=token,
        status__in=[Job.Status.LEASED, Job.Status.SENDING],
    ).update(lease_expires_at=observed_at + timedelta(seconds=lease_seconds))
    if updated != 1:
        raise LeaseError("Lease token is stale or the job is no longer leased.")


def mark_sending(job_id: uuid.UUID, token: uuid.UUID) -> None:
    updated = Job.objects.filter(
        pk=job_id,
        lease_token=token,
        status=Job.Status.LEASED,
    ).update(status=Job.Status.SENDING)
    if updated != 1:
        raise LeaseError("Cannot enter SENDING with a stale lease.")


def succeed(job_id: uuid.UUID, token: uuid.UUID) -> None:
    updated = (
        Job.objects.filter(pk=job_id, lease_token=token)
        .filter(status__in=[Job.Status.LEASED, Job.Status.SENDING])
        .update(
            status=Job.Status.SUCCEEDED,
            lease_token=None,
            lease_expires_at=None,
            last_error_code="",
        )
    )
    if updated != 1:
        raise LeaseError("Cannot complete a job with a stale lease.")


def suppress(job_id: uuid.UUID, token: uuid.UUID, *, code: str) -> None:
    updated = Job.objects.filter(pk=job_id, lease_token=token).update(
        status=Job.Status.SUPPRESSED,
        lease_token=None,
        lease_expires_at=None,
        last_error_code=code[:100],
    )
    if updated != 1:
        raise LeaseError("Cannot suppress a job with a stale lease.")


def fail_retryable(
    job_id: uuid.UUID,
    token: uuid.UUID,
    *,
    code: str,
    delay_seconds: int,
) -> None:
    observed_at = now()
    updated = Job.objects.filter(pk=job_id, lease_token=token).update(
        status=Job.Status.RETRY_WAIT,
        run_after=observed_at + timedelta(seconds=max(delay_seconds, 1)),
        lease_token=None,
        lease_expires_at=None,
        last_error_code=code[:100],
    )
    if updated != 1:
        raise LeaseError("Cannot reschedule a job with a stale lease.")


def fail_permanent(job_id: uuid.UUID, token: uuid.UUID, *, code: str) -> None:
    updated = Job.objects.filter(pk=job_id, lease_token=token).update(
        status=Job.Status.FAILED,
        lease_token=None,
        lease_expires_at=None,
        last_error_code=code[:100],
    )

    if updated != 1:
        raise LeaseError("Cannot fail a job with a stale lease.")


def mark_unknown(job_id: uuid.UUID, token: uuid.UUID, *, code: str) -> None:
    updated = Job.objects.filter(pk=job_id, lease_token=token).update(
        status=Job.Status.UNKNOWN,
        lease_token=None,
        lease_expires_at=None,
        last_error_code=code[:100],
    )
    if updated != 1:
        raise LeaseError("Cannot mark UNKNOWN with a stale lease.")
