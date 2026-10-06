from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from accounts.models import User
from boards.models import BoardColumn, BoardMembership
from core.clock import now
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Prefetch
from notifications.jobs import enqueue_job
from notifications.models import Job, Notification
from workitems.models import CommitmentRevision, Review, Submission, Task

from .models import ReportSnapshot

DEFINITION_VERSION = 1


def manager_board_ids(user: User) -> set[str]:
    return {
        str(value)
        for value in BoardMembership.objects.filter(
            user=user,
            role=BoardMembership.Role.MANAGER,
            is_active=True,
            board__archived=False,
        ).values_list("board_id", flat=True)
    }


def snapshot_scope_authorized(snapshot: ReportSnapshot, user: User) -> bool:
    return set(str(value) for value in snapshot.scope_board_ids).issubset(manager_board_ids(user))


def _percent(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    value = (Decimal(numerator) * Decimal("100") / Decimal(denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return f"{value:.2f}"


def _category(submitted_at: datetime, due_at: datetime, threshold_minutes: int) -> str:
    threshold = due_at - timedelta(minutes=threshold_minutes)
    if submitted_at <= threshold:
        return "early"
    if submitted_at <= due_at:
        return "on_time"
    return "late"


def _day_bounds(report_date: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start_local = datetime.combine(report_date, time.min, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def calculate_report(
    *,
    recipient: User,
    report_date: date,
    observed_at: datetime,
    scope_board_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    zone = ZoneInfo(settings.DEPLOYMENT["timezone"])
    scope = scope_board_ids or manager_board_ids(recipient)
    if not scope:
        return [], {}

    start_utc, end_utc = _day_bounds(report_date, zone)
    commitments = CommitmentRevision.objects.order_by("revision")
    submissions = Submission.objects.select_related("review").order_by("submitted_at")
    tasks = (
        Task.objects.filter(
            board_id__in=scope,
            committed_at__isnull=False,
            is_archived=False,
            column__is_archived=False,
            commitments__revision=1,
            commitments__due_at__gte=start_utc,
            commitments__due_at__lt=end_utc,
        )
        .select_related("board", "column", "current_owner", "original_owner", "current_commitment")
        .prefetch_related(
            Prefetch("commitments", queryset=commitments, to_attr="report_commitments"),
            Prefetch("submissions", queryset=submissions, to_attr="report_submissions"),
        )
        .distinct()
        .order_by("board_id", "id")
    )

    threshold_minutes = int(settings.DEPLOYMENT["early_threshold_minutes"])
    rows: list[dict[str, Any]] = []
    for task in tasks:
        originals = [item for item in task.report_commitments if item.revision == 1]
        if not originals:
            continue
        original = originals[0]
        current_submission = next(
            (item for item in task.report_submissions if item.is_current),
            None,
        )
        accepted_submission = None
        pending_review = False
        if current_submission is not None:
            try:
                review = current_submission.review
            except Review.DoesNotExist:
                review = None
            if review is None:
                pending_review = True
            elif review.decision == Review.Decision.ACCEPTED:
                accepted_submission = current_submission

        original_category = None
        revised_category = None
        difference_minutes = None
        if accepted_submission is not None:
            original_category = _category(
                accepted_submission.submitted_at,
                original.due_at,
                threshold_minutes,
            )
            difference_minutes = round(
                (original.due_at - accepted_submission.submitted_at).total_seconds() / 60,
                2,
            )
            current_due = (
                task.current_commitment.due_at
                if task.current_commitment is not None
                else original.due_at
            )
            revised_category = _category(
                accepted_submission.submitted_at,
                current_due,
                threshold_minutes,
            )

        previous_accepted = any(
            (not item.is_current)
            and hasattr(item, "review")
            and item.review.decision == Review.Decision.ACCEPTED
            for item in task.report_submissions
        )
        overdue = (
            not task.is_cancelled
            and accepted_submission is None
            and not pending_review
            and original.due_at <= observed_at
        )
        upcoming = (
            not task.is_cancelled
            and accepted_submission is None
            and not pending_review
            and original.due_at > observed_at
        )
        rows.append(
            {
                "task_id": str(task.id),
                "board_id": str(task.board_id),
                "title": task.title,
                "priority": task.priority,
                "state": task.column.state,
                "cancelled": task.is_cancelled,
                "cancellation_reason": task.cancelled_reason if task.is_cancelled else "",
                "original_owner_id": str(original.owner_id),
                "current_owner_id": str(task.current_owner_id) if task.current_owner_id else None,
                "original_due_at": original.due_at.isoformat(),
                "revised_due_at": (
                    task.current_commitment.due_at.isoformat()
                    if task.current_commitment is not None
                    else original.due_at.isoformat()
                ),
                "commitment_revisions": len(task.report_commitments),
                "accepted_submission_at": (
                    accepted_submission.submitted_at.isoformat()
                    if accepted_submission is not None
                    else None
                ),
                "original_category": original_category,
                "revised_category": revised_category,
                "difference_minutes": difference_minutes,
                "pending_review": pending_review,
                "overdue": overdue,
                "upcoming": upcoming,
                "blocked": task.column.state == BoardColumn.State.BLOCKED,
                "reopened": previous_accepted and accepted_submission is None,
                "evidence_links": (
                    list(accepted_submission.evidence_links)
                    if accepted_submission is not None
                    else []
                ),
                "result_summary": (
                    accepted_submission.result_summary if accepted_submission is not None else None
                ),
            }
        )

    net_rows = [row for row in rows if not row["cancelled"]]
    gross_rows = rows
    early = sum(row["original_category"] == "early" for row in net_rows)
    on_time = sum(row["original_category"] == "on_time" for row in net_rows)
    late = sum(row["original_category"] == "late" for row in net_rows)
    pending = sum(bool(row["pending_review"]) for row in net_rows)
    unfinished = sum(
        row["original_category"] is None and not row["pending_review"] for row in net_rows
    )
    overdue_count = sum(bool(row["overdue"]) for row in net_rows)
    upcoming_count = sum(bool(row["upcoming"]) for row in net_rows)
    accepted_results = sum(row["original_category"] is not None for row in net_rows)
    cancellations = len(rows) - len(net_rows)
    original_adherent = early + on_time
    gross_adherent = sum(row["original_category"] in {"early", "on_time"} for row in gross_rows)
    matured_rows = [
        row for row in net_rows if datetime.fromisoformat(row["original_due_at"]) <= observed_at
    ]
    matured_adherent = sum(row["original_category"] in {"early", "on_time"} for row in matured_rows)
    revised_adherent = sum(row["revised_category"] in {"early", "on_time"} for row in net_rows)

    tomorrow = report_date + timedelta(days=1)
    tomorrow_start, tomorrow_end = _day_bounds(tomorrow, zone)
    tomorrow_tasks = list(
        Task.objects.filter(
            board_id__in=scope,
            is_cancelled=False,
            is_archived=False,
            column__is_archived=False,
            current_commitment__due_at__gte=tomorrow_start,
            current_commitment__due_at__lt=tomorrow_end,
        )
        .values("id", "title", "priority", "current_owner_id")
        .order_by("current_commitment__due_at")[:100]
    )

    metrics = {
        "definition_version": DEFINITION_VERSION,
        "net_cohort": len(net_rows),
        "gross_cohort": len(gross_rows),
        "early": early,
        "on_time": on_time,
        "late": late,
        "pending_review": pending,
        "unfinished": unfinished,
        "overdue_unfinished": overdue_count,
        "upcoming": upcoming_count,
        "accepted_results": accepted_results,
        "cancelled": cancellations,
        "original_deadline_adherence_percent": _percent(original_adherent, len(net_rows)),
        "gross_commitment_adherence_percent": _percent(gross_adherent, len(gross_rows)),
        "matured_cohort": len(matured_rows),
        "matured_adherence_percent": _percent(matured_adherent, len(matured_rows)),
        "revised_deadline_adherence_percent": _percent(revised_adherent, len(net_rows)),
        "provisional": pending > 0,
        "tomorrow": [
            {
                "task_id": str(item["id"]),
                "title": item["title"],
                "priority": item["priority"],
                "current_owner_id": (
                    str(item["current_owner_id"]) if item["current_owner_id"] is not None else None
                ),
            }
            for item in tomorrow_tasks
        ],
    }
    return rows, metrics


def _scheduled_for(report_date: date) -> datetime:
    zone = ZoneInfo(settings.DEPLOYMENT["timezone"])
    hour_text, minute_text = settings.DEPLOYMENT["manager_report_time"].split(":", 1)
    return datetime.combine(
        report_date,
        time(int(hour_text), int(minute_text)),
        tzinfo=zone,
    ).astimezone(UTC)


def _snapshot_message(snapshot: ReportSnapshot) -> str:
    metrics = snapshot.metrics
    label = "DELAYED " if snapshot.delayed else ""
    adherence = metrics.get("original_deadline_adherence_percent")
    adherence_text = "N/A" if adherence is None else f"{adherence}%"
    return (
        f"{label}Manager report {snapshot.report_date.isoformat()}\n"
        f"Observed: {snapshot.observation_started_at.isoformat()}\n"
        f"Early: {metrics.get('early', 0)} | On time: {metrics.get('on_time', 0)} | "
        f"Late: {metrics.get('late', 0)}\n"
        f"Pending review: {metrics.get('pending_review', 0)} | "
        f"Overdue unfinished: {metrics.get('overdue_unfinished', 0)}\n"
        f"Original deadline adherence: {adherence_text}"
    )[:3000]


def create_snapshot(*, recipient: User, report_date: date) -> ReportSnapshot | None:
    observed_at = now()
    scheduled_for = _scheduled_for(report_date)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        scope = manager_board_ids(recipient)
        if not scope:
            return None
        rows, metrics = calculate_report(
            recipient=recipient,
            report_date=report_date,
            observed_at=observed_at,
            scope_board_ids=scope,
        )
        generated_at = now()
        snapshot = ReportSnapshot.objects.create(
            recipient=recipient,
            report_date=report_date,
            scheduled_for=scheduled_for,
            observation_started_at=observed_at,
            generated_at=generated_at,
            timezone=settings.DEPLOYMENT["timezone"],
            scope_board_ids=sorted(scope),
            definition_version=DEFINITION_VERSION,
            generation=1,
            rows=rows,
            metrics=metrics,
            delayed=observed_at > scheduled_for + timedelta(seconds=60),
        )
    return snapshot


def create_scheduled_manager_report(job: Job) -> ReportSnapshot | None:
    recipient_id = job.payload.get("recipient_id")
    report_date_value = job.payload.get("report_date")
    recipient = User.objects.filter(pk=recipient_id, is_active=True).first()
    if recipient is None or not isinstance(report_date_value, str):
        return None
    try:
        report_date = date.fromisoformat(report_date_value)
    except ValueError:
        return None

    snapshot = create_snapshot(recipient=recipient, report_date=report_date)
    if snapshot is None:
        return None
    notification, _ = Notification.objects.get_or_create(
        semantic_key=job.semantic_key,
        defaults={
            "recipient": recipient,
            "task": None,
            "report_snapshot": snapshot,
            "kind": "manager_report",
            "scheduled_for": job.run_after,
            "observed_at": snapshot.observation_started_at,
            "status": Notification.Status.QUEUED,
            "destination_generation": recipient.slack_destination_generation,
            "message_preview": _snapshot_message(snapshot),
        },
    )
    if settings.DEPLOYMENT["slack_mode"] in {"dry_run", "live"}:
        enqueue_job(
            semantic_key=f"slack:{notification.id}:{notification.destination_generation}",
            job_type="slack_delivery",
            run_after=now(),
            payload={"notification_id": str(notification.id)},
            generation=notification.destination_generation,
        )
    return snapshot
