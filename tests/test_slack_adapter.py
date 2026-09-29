from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
import requests
from boards.models import Board, BoardColumn, BoardMembership
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from notifications.models import Job, Notification, SlackPilotApproval
from notifications.slack import deliver
from workitems.services import commit_task, create_task

User = get_user_model()

pytestmark = pytest.mark.django_db(transaction=True)

STANDARD_COLUMNS = [
    (BoardColumn.State.BACKLOG, "Backlog"),
    (BoardColumn.State.TODO, "To Do"),
    (BoardColumn.State.IN_PROGRESS, "In Progress"),
    (BoardColumn.State.BLOCKED, "Blocked"),
    (BoardColumn.State.REVIEW, "Review"),
    (BoardColumn.State.DONE, "Done"),
]


class FakeResponse:
    def __init__(
        self,
        payload: Any,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        malformed: bool = False,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.malformed = malformed

    def json(self) -> Any:
        if self.malformed:
            raise ValueError("malformed")
        return self.payload


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("Unexpected Slack HTTP call")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def make_live_fixture():
    admin = User.objects.create_user(username="slack-admin", password=None, is_staff=True)
    manager = User.objects.create_user(username="slack-manager", password=None)
    member = User.objects.create_user(username="slack-member", password=None)
    board = Board.objects.create(name="Slack board", created_by=admin)
    for position, (state, label) in enumerate(STANDARD_COLUMNS):
        BoardColumn.objects.create(board=board, state=state, name=label, position=position)
    for user, role in (
        (manager, BoardMembership.Role.MANAGER),
        (member, BoardMembership.Role.MEMBER),
    ):
        BoardMembership.objects.create(
            board=board,
            user=user,
            role=role,
            created_by=admin,
        )

    due = timezone.now() + timedelta(hours=2)
    task = create_task(
        actor=member,
        board_id=board.id,
        title="Slack delivery task",
        priority=2,
        owner_id=member.id,
        draft_due_at=due,
        draft_acceptance_criteria="Evidence is present.",
    )
    board.refresh_from_db()
    task = commit_task(
        actor=manager,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        owner_id=member.id,
        due_at=due,
        acceptance_criteria="Evidence is present.",
        reason="Commit Slack test task",
    )

    member.slack_workspace_id = "T-TEST"
    member.slack_member_id = "U-TEST"
    member.slack_verified_at = timezone.now()
    member.slack_verified_by = admin
    member.save(
        update_fields=[
            "slack_workspace_id",
            "slack_member_id",
            "slack_verified_at",
            "slack_verified_by",
        ]
    )
    SlackPilotApproval.objects.create(
        recipient=member,
        destination_generation=member.slack_destination_generation,
        sample_hash="0" * 64,
        approved_by=admin,
    )

    notification = Notification.objects.create(
        semantic_key=f"slack-notification:{task.id}",
        recipient=member,
        task=task,
        kind="assignment_notification",
        scheduled_for=timezone.now(),
        observed_at=timezone.now(),
        status=Notification.Status.QUEUED,
        destination_generation=member.slack_destination_generation,
        message_preview="Assigned: Slack delivery task",
    )
    token = uuid.uuid4()
    job = Job.objects.create(
        semantic_key=f"slack-job:{notification.id}",
        job_type="slack_delivery",
        run_after=timezone.now(),
        status=Job.Status.LEASED,
        attempts=1,
        lease_token=token,
        lease_expires_at=timezone.now() + timedelta(minutes=2),
        payload={"notification_id": str(notification.id)},
        generation=member.slack_destination_generation,
    )
    return admin, member, task, notification, job, token


def configure_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(settings.DEPLOYMENT, "slack_mode", "live")
    monkeypatch.setitem(settings.DEPLOYMENT, "environment", "pilot")
    monkeypatch.setitem(settings.DEPLOYMENT, "restore_mode", False)
    monkeypatch.setenv("PRODUCTIVITY_OUTBOUND_KILL_SWITCH", "0")
    monkeypatch.setattr("notifications.slack._token", lambda: "test-token")


def test_dry_run_never_calls_http(monkeypatch: pytest.MonkeyPatch):
    _, _, _, notification, job, token = make_live_fixture()
    monkeypatch.setitem(settings.DEPLOYMENT, "slack_mode", "dry_run")
    client = FakeClient([])

    deliver(job, token, client=client)
    notification.refresh_from_db()
    job.refresh_from_db()

    assert client.calls == []
    assert notification.status == Notification.Status.DRY_RUN
    assert job.status == Job.Status.SUCCEEDED


def test_live_success_records_conversation_and_message(monkeypatch: pytest.MonkeyPatch):
    _, _, _, notification, job, token = make_live_fixture()
    configure_live(monkeypatch)
    client = FakeClient(
        [
            FakeResponse({"ok": True, "team_id": "T-TEST"}),
            FakeResponse({"ok": True, "channel": {"id": "D-TEST"}}),
            FakeResponse({"ok": True, "ts": "123.456"}),
        ]
    )

    deliver(job, token, client=client)
    notification.refresh_from_db()
    job.refresh_from_db()

    assert notification.status == Notification.Status.SENT
    assert notification.conversation_id == "D-TEST"
    assert notification.message_ts == "123.456"
    assert job.status == Job.Status.SUCCEEDED


@pytest.mark.parametrize(
    ("responses", "notification_status", "job_status", "error_code"),
    [
        (
            [FakeResponse({"ok": False, "error": "invalid_auth"})],
            Notification.Status.FAILED,
            Job.Status.FAILED,
            "workspace_mismatch",
        ),
        (
            [
                FakeResponse({"ok": True, "team_id": "T-TEST"}),
                FakeResponse(
                    {"ok": False},
                    status_code=429,
                    headers={"Retry-After": "2"},
                ),
            ],
            Notification.Status.QUEUED,
            Job.Status.RETRY_WAIT,
            "slack_429",
        ),
        (
            [requests.ConnectTimeout("connect timeout")],
            Notification.Status.QUEUED,
            Job.Status.RETRY_WAIT,
            "",
        ),
        (
            [
                FakeResponse({"ok": True, "team_id": "T-TEST"}),
                FakeResponse({}, malformed=True),
            ],
            Notification.Status.QUEUED,
            Job.Status.RETRY_WAIT,
            "",
        ),
        (
            [
                FakeResponse({"ok": True, "team_id": "T-TEST"}),
                FakeResponse({"ok": True, "channel": {"id": "D-TEST"}}),
                requests.ReadTimeout("ambiguous post timeout"),
            ],
            Notification.Status.UNKNOWN,
            Job.Status.UNKNOWN,
            "ambiguous_delivery",
        ),
    ],
)
def test_fake_slack_failure_matrix(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[Any],
    notification_status: str,
    job_status: str,
    error_code: str,
):
    _, _, _, notification, job, token = make_live_fixture()
    configure_live(monkeypatch)
    client = FakeClient(responses)

    deliver(job, token, client=client)
    notification.refresh_from_db()
    job.refresh_from_db()

    assert notification.status == notification_status
    assert job.status == job_status
    if error_code:
        assert notification.error_code == error_code or job.last_error_code == error_code


def test_cached_dm_channel_skips_conversations_open(monkeypatch: pytest.MonkeyPatch):
    _, member, task, notification, job, token = make_live_fixture()
    configure_live(monkeypatch)
    Notification.objects.create(
        semantic_key="prior-sent",
        recipient=member,
        task=task,
        kind="assignment_notification",
        scheduled_for=timezone.now() - timedelta(minutes=1),
        observed_at=timezone.now() - timedelta(minutes=1),
        status=Notification.Status.SENT,
        destination_generation=member.slack_destination_generation,
        message_preview="Earlier message",
        conversation_id="D-CACHED",
        message_ts="100.1",
    )
    client = FakeClient(
        [
            FakeResponse({"ok": True, "team_id": "T-TEST"}),
            FakeResponse({"ok": True, "ts": "200.2"}),
        ]
    )

    deliver(job, token, client=client)
    notification.refresh_from_db()

    assert notification.status == Notification.Status.SENT
    assert notification.conversation_id == "D-CACHED"
    assert not any("conversations.open" in url for url in client.calls)
