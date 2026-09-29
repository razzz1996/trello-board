from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Protocol

import requests
from boards.models import BoardColumn, BoardMembership
from core.clock import now
from django.conf import settings
from requests import Response

from . import jobs
from .models import Job, Notification, SlackPilotApproval


class HttpClient(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        timeout: tuple[float, float],
    ) -> Response: ...


class SlackDeliveryError(RuntimeError):
    pass


SAFE_BACKOFF_SECONDS = [60, 120, 240, 480, 960]


def _token() -> str:
    path_value = os.environ.get("PRODUCTIVITY_SLACK_TOKEN_FILE")
    if not path_value:
        raise SlackDeliveryError("Slack token file is not configured.")
    path = Path(path_value)
    if not path.is_file():
        raise SlackDeliveryError("Slack token file does not exist.")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise SlackDeliveryError("Slack token file is empty.")
    return token


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _json(response: Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError as exc:
        raise SlackDeliveryError("Slack returned malformed JSON.") from exc
    if not isinstance(value, dict):
        raise SlackDeliveryError("Slack returned an unexpected response.")
    return value


def _eligible(notification: Notification) -> bool:
    recipient = notification.recipient
    task = notification.task
    if (
        not recipient.is_active
        or notification.destination_generation != recipient.slack_destination_generation
    ):
        return False
    if task is None:
        if notification.kind == "personal_digest":
            return True
        if notification.kind == "manager_report" and notification.report_snapshot_id:
            from reports.services import snapshot_scope_authorized

            snapshot = notification.report_snapshot
            return snapshot is not None and snapshot_scope_authorized(snapshot, recipient)
        return False
    if task.is_cancelled:
        return False
    membership = BoardMembership.objects.filter(
        board=task.board,
        user=recipient,
        is_active=True,
    ).first()
    if membership is None:
        return False
    if notification.kind == "needs_assignment":
        return (
            membership.role == BoardMembership.Role.MANAGER
            and task.current_owner_id is None
            and task.committed_at is None
        )
    if notification.kind == "review_request":
        submission = (
            task.submissions.filter(is_current=True, review__isnull=True)
            .exclude(accountable_owner=recipient)
            .exclude(submitting_actor=recipient)
            .first()
        )
        return (
            membership.role == BoardMembership.Role.MANAGER
            and task.column.state == BoardColumn.State.REVIEW
            and submission is not None
        )
    if notification.kind == "overdue_manager_escalation":
        return (
            membership.role == BoardMembership.Role.MANAGER
            and task.column.state
            in {
                BoardColumn.State.TODO,
                BoardColumn.State.IN_PROGRESS,
                BoardColumn.State.BLOCKED,
            }
            and task.current_commitment is not None
            and task.current_commitment.due_at <= now()
        )
    if task.current_owner_id != recipient.id:
        return False
    if notification.kind == "due_reminder":
        return task.column.state in {
            BoardColumn.State.TODO,
            BoardColumn.State.IN_PROGRESS,
            BoardColumn.State.BLOCKED,
        }
    if notification.kind == "overdue_escalation":
        return task.column.state in {
            BoardColumn.State.TODO,
            BoardColumn.State.IN_PROGRESS,
            BoardColumn.State.BLOCKED,
        }
    if notification.kind == "assignment_notification":
        return task.column.state != BoardColumn.State.DONE
    return True


def _live_authorized(notification: Notification) -> bool:
    if settings.DEPLOYMENT["environment"] != "pilot":
        return False
    if settings.DEPLOYMENT["restore_mode"]:
        return False
    if os.environ.get("PRODUCTIVITY_OUTBOUND_KILL_SWITCH", "0") == "1":
        return False
    recipient = notification.recipient
    if (
        not recipient.slack_workspace_id
        or not recipient.slack_member_id
        or not recipient.slack_verified_at
    ):
        return False
    return SlackPilotApproval.objects.filter(
        recipient=recipient,
        destination_generation=notification.destination_generation,
        active=True,
    ).exists()


def _retry_or_fail(job: Job, lease_token: uuid.UUID, code: str) -> None:
    if job.attempts <= len(SAFE_BACKOFF_SECONDS):
        jobs.fail_retryable(
            job.id,
            lease_token,
            code=code,
            delay_seconds=SAFE_BACKOFF_SECONDS[job.attempts - 1],
        )
    else:
        jobs.fail_permanent(job.id, lease_token, code=code)


def deliver(job: Job, lease_token: uuid.UUID, *, client: HttpClient | None = None) -> None:
    notification_id = job.payload.get("notification_id")
    notification = (
        Notification.objects.select_related(
            "recipient",
            "task__board",
            "task__column",
            "report_snapshot",
        )
        .filter(pk=notification_id)
        .first()
    )
    if notification is None:
        jobs.suppress(job.id, lease_token, code="notification_missing")
        return
    if not _eligible(notification):
        notification.status = Notification.Status.SUPPRESSED
        notification.error_code = "stale_notification"
        notification.save(update_fields=["status", "error_code"])
        jobs.suppress(job.id, lease_token, code="stale_notification")
        return

    mode = settings.DEPLOYMENT["slack_mode"]
    if mode == "off":
        notification.status = Notification.Status.SUPPRESSED
        notification.error_code = "slack_off"
        notification.save(update_fields=["status", "error_code"])
        jobs.suppress(job.id, lease_token, code="slack_off")
        return
    if mode == "dry_run":
        notification.status = Notification.Status.DRY_RUN
        notification.observed_at = notification.observed_at or now()
        notification.save(update_fields=["status", "observed_at"])
        jobs.succeed(job.id, lease_token)
        return
    if not _live_authorized(notification):
        notification.status = Notification.Status.FAILED
        notification.error_code = "live_not_approved"
        notification.save(update_fields=["status", "error_code"])
        jobs.fail_permanent(job.id, lease_token, code="live_not_approved")
        return

    http = client or requests.Session()
    token = _token()
    headers = _headers(token)
    try:
        auth_response = http.post(
            "https://slack.com/api/auth.test",
            headers=headers,
            data={},
            timeout=(5.0, 15.0),
        )
        auth_data = _json(auth_response)
        if (
            not auth_data.get("ok")
            or auth_data.get("team_id") != notification.recipient.slack_workspace_id
        ):
            notification.status = Notification.Status.FAILED
            notification.error_code = "workspace_mismatch"
            notification.save(update_fields=["status", "error_code"])
            jobs.fail_permanent(job.id, lease_token, code="workspace_mismatch")
            return

        channel = (
            Notification.objects.filter(
                recipient=notification.recipient,
                destination_generation=notification.destination_generation,
                conversation_id__gt="",
            )
            .exclude(pk=notification.pk)
            .order_by("-created_at")
            .values_list("conversation_id", flat=True)
            .first()
        )
        if not channel:
            open_response = http.post(
                "https://slack.com/api/conversations.open",
                headers=headers,
                json={"users": notification.recipient.slack_member_id},
                timeout=(5.0, 15.0),
            )
            if open_response.status_code == 429:
                delay = int(open_response.headers.get("Retry-After", "60"))
                jobs.fail_retryable(
                    job.id,
                    lease_token,
                    code="slack_429",
                    delay_seconds=max(delay, 1),
                )
                return
            open_data = _json(open_response)
            if not open_data.get("ok"):
                code = str(open_data.get("error", "slack_open_failed"))
                jobs.fail_permanent(job.id, lease_token, code=code)
                notification.status = Notification.Status.FAILED
                notification.error_code = code[:100]
                notification.save(update_fields=["status", "error_code"])
                return
            channel = str(open_data["channel"]["id"])
    except requests.ConnectTimeout:
        _retry_or_fail(job, lease_token, "preconnect_timeout")
        return
    except requests.RequestException:
        _retry_or_fail(job, lease_token, "conversation_open_transport")
        return
    except (KeyError, TypeError, SlackDeliveryError):
        _retry_or_fail(job, lease_token, "conversation_open_malformed")
        return

    message = notification.message_preview[:2800]
    base_url = settings.DEPLOYMENT.get("private_base_url")
    task = notification.task
    if base_url and task is not None:
        message += f"\nCurrent state: {base_url.rstrip('/')}/boards/{task.board_id}"
    if notification.observed_at:
        message += f"\nObserved: {notification.observed_at.isoformat()}"

    attempt_id = uuid.uuid4()
    notification.attempt_uuid = attempt_id
    notification.save(update_fields=["attempt_uuid"])
    jobs.mark_sending(job.id, lease_token)
    try:
        response = http.post(
            "https://slack.com/api/chat.postMessage",
            headers=headers,
            json={
                "channel": channel,
                "text": message[:3000],
                "unfurl_links": False,
                "unfurl_media": False,
            },
            timeout=(5.0, 15.0),
        )
        if response.status_code == 429:
            delay = int(response.headers.get("Retry-After", "60"))
            notification.status = Notification.Status.QUEUED
            notification.error_code = "slack_429"
            notification.save(update_fields=["status", "error_code"])
            jobs.fail_retryable(job.id, lease_token, code="slack_429", delay_seconds=max(delay, 1))
            return
        data = _json(response)
        if not data.get("ok"):
            code = str(data.get("error", "slack_post_failed"))
            notification.status = Notification.Status.FAILED
            notification.error_code = code[:100]
            notification.save(update_fields=["status", "error_code"])
            jobs.fail_permanent(job.id, lease_token, code=code)
            return
        notification.status = Notification.Status.SENT
        notification.conversation_id = channel
        notification.message_ts = str(data.get("ts", ""))
        notification.error_code = ""
        notification.save(update_fields=["status", "conversation_id", "message_ts", "error_code"])
        jobs.succeed(job.id, lease_token)
    except requests.ConnectTimeout:
        notification.status = Notification.Status.UNKNOWN
        notification.error_code = "ambiguous_connect_timeout"
        notification.save(update_fields=["status", "error_code"])
        jobs.mark_unknown(job.id, lease_token, code="ambiguous_connect_timeout")
    except (requests.RequestException, SlackDeliveryError, ValueError, KeyError, TypeError):
        notification.status = Notification.Status.UNKNOWN
        notification.error_code = "ambiguous_delivery"
        notification.save(update_fields=["status", "error_code"])
        jobs.mark_unknown(job.id, lease_token, code="ambiguous_delivery")
