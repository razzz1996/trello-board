from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from boards.models import Board, BoardColumn, BoardMembership
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.utils import timezone
from notifications.models import Job, Notification
from notifications.scheduler import scheduler_tick
from notifications.worker import worker_tick
from rest_framework.test import APIClient
from schedules.models import Occurrence, Schedule, ScheduleRevision
from workitems.errors import DomainError
from workitems.models import ChecklistItem, CommitmentRevision, Submission, Task
from workitems.recurrence import _advance, configure_recurrence, trigger_recurrence
from workitems.services import commit_task, create_task

User = get_user_model()
pytestmark = pytest.mark.django_db(transaction=True)

STANDARD_COLUMNS = [
    (BoardColumn.State.BACKLOG, "Inbox"),
    (BoardColumn.State.TODO, "To Do"),
    (BoardColumn.State.IN_PROGRESS, "In Progress"),
    (BoardColumn.State.BLOCKED, "Later"),
    (BoardColumn.State.DONE, "Done"),
]


def make_board():
    admin = User.objects.create_user(
        username="delete-recurrence-admin",
        password=None,
        is_staff=True,
    )
    member = User.objects.create_user(
        username="delete-recurrence-member",
        password=None,
    )
    board = Board.objects.create(name="Deletion and recurrence", created_by=admin)
    for position, (state, label) in enumerate(STANDARD_COLUMNS):
        BoardColumn.objects.create(
            board=board,
            state=state,
            name=label,
            position=position,
        )
    BoardMembership.objects.create(
        board=board,
        user=admin,
        role=BoardMembership.Role.MANAGER,
        created_by=admin,
    )
    BoardMembership.objects.create(
        board=board,
        user=member,
        role=BoardMembership.Role.MEMBER,
        created_by=admin,
    )
    return admin, member, board


def test_any_board_user_can_delete_card_and_positions_resequence():
    _, member, board = make_board()
    first = create_task(actor=member, board_id=board.id, title="First")
    middle = create_task(actor=member, board_id=board.id, title="Middle")
    last = create_task(actor=member, board_id=board.id, title="Last")
    board.refresh_from_db()

    client = APIClient()
    client.force_authenticate(user=member)
    payload = {
        "expected_version": middle.row_version,
        "expected_board_revision": board.revision,
    }
    response = client.post(
        f"/api/v1/tasks/{middle.id}/delete",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="delete-middle-card",
    )
    replay = client.post(
        f"/api/v1/tasks/{middle.id}/delete",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="delete-middle-card",
    )

    assert response.status_code == 200
    assert replay.status_code == 200
    assert response.json() == replay.json()
    assert not Task.objects.filter(pk=middle.id).exists()
    remaining = list(
        Task.objects.filter(pk__in=[first.id, last.id])
        .order_by("position")
        .values_list("title", "position")
    )
    assert remaining == [("First", 0), ("Last", 1)]
    board.refresh_from_db()
    assert board.audit_events.filter(action="delete_task", task__isnull=True).count() == 1


def test_stale_card_delete_is_rejected_without_removing_card():
    _, member, board = make_board()
    task = create_task(actor=member, board_id=board.id, title="Keep me")
    board.refresh_from_db()

    client = APIClient()
    client.force_authenticate(user=member)
    response = client.post(
        f"/api/v1/tasks/{task.id}/delete",
        {
            "expected_version": task.row_version,
            "expected_board_revision": board.revision - 1,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="stale-card-delete",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "stale_state"
    assert Task.objects.filter(pk=task.id).exists()


def test_only_admin_can_delete_board_and_related_rows_are_purged():
    admin, member, board = make_board()
    task = create_task(actor=member, board_id=board.id, title="Delete with board")
    observed = timezone.now()
    schedule = Schedule.objects.create(
        board=board,
        name="Temporary recurring schedule",
        timezone="Asia/Manila",
        active=True,
        created_by=admin,
    )
    revision = ScheduleRevision.objects.create(
        schedule=schedule,
        revision=1,
        rule={"frequency": "daily"},
        template_fields={"title": "Generated card"},
        effective_base_period=observed.date().isoformat(),
        actor=admin,
        reason="Deletion test",
    )
    schedule.current_revision = revision
    schedule.save(update_fields=["current_revision"])
    Occurrence.objects.create(
        schedule=schedule,
        period_key=observed.date().isoformat(),
        schedule_revision=revision,
        task=task,
        release_at=observed,
        due_at=observed + timedelta(hours=1),
    )
    Job.objects.create(
        semantic_key=f"schedule-delete:{schedule.id}",
        job_type="recurrence_scan",
        run_after=observed,
        payload={"schedule_id": str(schedule.id)},
    )

    member_client = APIClient()
    member_client.force_authenticate(user=member)
    forbidden = member_client.post(
        f"/api/v1/boards/{board.id}/delete",
        {"confirm_name": board.name},
        format="json",
        HTTP_IDEMPOTENCY_KEY="member-delete-board",
    )
    assert forbidden.status_code == 403
    assert Board.objects.filter(pk=board.id).exists()

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    mismatch = admin_client.post(
        f"/api/v1/boards/{board.id}/delete",
        {"confirm_name": "wrong name"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="wrong-board-confirmation",
    )
    assert mismatch.status_code == 400
    assert Board.objects.filter(pk=board.id).exists()

    payload = {"confirm_name": board.name}
    deleted = admin_client.post(
        f"/api/v1/boards/{board.id}/delete",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="admin-delete-board",
    )
    replay = admin_client.post(
        f"/api/v1/boards/{board.id}/delete",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="admin-delete-board",
    )

    assert deleted.status_code == 200
    assert replay.status_code == 200
    assert deleted.json() == replay.json()
    assert not Board.objects.filter(pk=board.id).exists()
    assert not Task.objects.filter(pk=task.id).exists()
    assert not Schedule.objects.filter(pk=schedule.id).exists()
    assert not Occurrence.objects.filter(schedule_id=schedule.id).exists()
    assert not Job.objects.filter(payload__schedule_id=str(schedule.id)).exists()


def test_recurrence_configuration_rejects_missing_or_past_date():
    _, member, board = make_board()
    task = create_task(actor=member, board_id=board.id, title="Repeat validation")

    with pytest.raises(DomainError) as missing:
        configure_recurrence(
            task,
            frequency=Task.Recurrence.DAILY,
            next_at=None,
        )
    assert missing.value.code == "recurrence_date_required"

    with pytest.raises(DomainError) as past:
        configure_recurrence(
            task,
            frequency=Task.Recurrence.WEEKLY,
            next_at=timezone.now() - timedelta(minutes=1),
        )
    assert past.value.code == "recurrence_date_in_past"


def test_monthly_recurrence_preserves_anchor_day_across_short_months():
    zone = ZoneInfo("Asia/Manila")
    january = datetime(2027, 1, 31, 9, 30, tzinfo=zone)

    february = _advance(january, Task.Recurrence.MONTHLY, 31)
    march = _advance(february, Task.Recurrence.MONTHLY, 31)

    assert (february.year, february.month, february.day) == (2027, 2, 28)
    assert (march.year, march.month, march.day) == (2027, 3, 31)
    assert february.time() == january.time()
    assert march.time() == january.time()


def test_due_daily_recurrence_returns_card_to_inbox_and_resets_cycle():
    admin, member, board = make_board()
    task = create_task(
        actor=member,
        board_id=board.id,
        title="Daily opening checklist",
        owner_id=member.id,
        draft_due_at=timezone.now() + timedelta(hours=2),
    )
    observed = timezone.now()
    done = BoardColumn.objects.get(board=board, state=BoardColumn.State.DONE)
    task.column = done
    task.position = 0
    task.current_owner = member
    task.original_owner = member
    task.committed_at = observed - timedelta(hours=2)
    commitment = CommitmentRevision.objects.create(
        task=task,
        revision=1,
        owner=member,
        due_at=observed - timedelta(minutes=30),
        priority=task.priority,
        acceptance_criteria="Checklist completed.",
        required_checklist_snapshot=[],
        actor=admin,
        reason="Daily recurrence test",
    )
    task.current_commitment = commitment
    task.recurrence_frequency = Task.Recurrence.DAILY
    task.recurrence_next_at = observed - timedelta(minutes=1)
    task.recurrence_anchor_day = observed.day
    task.recurrence_generation = 4
    task.save()
    checklist = ChecklistItem.objects.create(
        task=task,
        text="Open the queue",
        required=True,
        position=0,
        checked=True,
    )
    submission = Submission.objects.create(
        task=task,
        commitment=commitment,
        accountable_owner=member,
        submitting_actor=member,
        result_summary="Completed.",
        evidence_links=["https://example.test/daily"],
        criteria_snapshot="Checklist completed.",
        checklist_snapshot=[],
        is_current=True,
    )
    board.refresh_from_db()
    original_board_revision = board.revision
    triggered = trigger_recurrence(
        task_id=task.id,
        generation=4,
        observed_at=observed,
    )

    assert triggered is True
    task.refresh_from_db()
    board.refresh_from_db()
    checklist.refresh_from_db()
    submission.refresh_from_db()

    assert task.column.state == BoardColumn.State.BACKLOG
    assert task.current_commitment_id is None
    assert task.committed_at is None
    assert task.original_owner_id is None
    assert task.current_owner_id == member.id
    assert task.draft_due_at is None
    assert checklist.checked is False
    assert submission.is_current is False
    assert task.recurrence_last_triggered_at == observed
    assert task.recurrence_next_at == observed - timedelta(minutes=1) + timedelta(days=1)
    assert task.recurrence_generation == 5
    assert board.revision == original_board_revision + 1
    assert (
        trigger_recurrence(
            task_id=task.id,
            generation=4,
            observed_at=observed,
        )
        is False
    )


def test_scheduler_and_worker_process_due_card_recurrence():
    _, member, board = make_board()
    task = create_task(actor=member, board_id=board.id, title="Weekly action")
    done = BoardColumn.objects.get(board=board, state=BoardColumn.State.DONE)
    observed = timezone.now()
    task.column = done
    task.position = 0
    task.recurrence_frequency = Task.Recurrence.WEEKLY
    task.recurrence_next_at = observed - timedelta(seconds=1)
    task.recurrence_anchor_day = observed.day
    task.recurrence_generation = 2
    task.save()
    Job.objects.all().delete()

    scheduler_result = scheduler_tick()
    job = Job.objects.get(
        job_type="task_recurrence",
        payload__task_id=str(task.id),
    )

    assert scheduler_result["task_recurrence_enqueued"] >= 1
    assert job.status == Job.Status.READY

    worker_result = worker_tick()
    task.refresh_from_db()
    job.refresh_from_db()

    assert worker_result["processed"] >= 1
    assert job.status == Job.Status.SUCCEEDED
    assert task.column.state == BoardColumn.State.BACKLOG
    assert task.recurrence_next_at is not None
    assert task.recurrence_next_at > observed


def test_board_user_can_configure_and_disable_recurrence_through_api():
    _, member, board = make_board()
    task = create_task(actor=member, board_id=board.id, title="API recurrence")
    board.refresh_from_db()
    next_at = timezone.now() + timedelta(days=2)

    client = APIClient()
    client.force_authenticate(user=member)
    configured = client.post(
        f"/api/v1/tasks/{task.id}/commands/edit_task",
        {
            "expected_version": task.row_version,
            "expected_board_revision": board.revision,
            "recurrence_frequency": "WEEKLY",
            "recurrence_next_at": next_at.isoformat(),
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="configure-weekly-card",
    )

    assert configured.status_code == 200
    configured_body = configured.json()
    assert configured_body["recurrence_frequency"] == "WEEKLY"
    assert configured_body["recurrence_next_at"] is not None

    board.refresh_from_db()
    task.refresh_from_db()
    disabled = client.post(
        f"/api/v1/tasks/{task.id}/commands/edit_task",
        {
            "expected_version": task.row_version,
            "expected_board_revision": board.revision,
            "recurrence_frequency": "NONE",
            "recurrence_next_at": None,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="disable-weekly-card",
    )
    assert disabled.status_code == 200
    assert disabled.json()["recurrence_frequency"] == "NONE"
    assert disabled.json()["recurrence_next_at"] is None


def test_card_delete_purges_committed_submission_and_notification_dependencies():
    admin, member, board = make_board()
    task = create_task(
        actor=member,
        board_id=board.id,
        title="Committed card to remove",
        owner_id=member.id,
    )
    observed = timezone.now()
    commitment = CommitmentRevision.objects.create(
        task=task,
        revision=1,
        owner=member,
        due_at=observed + timedelta(hours=1),
        priority=1,
        acceptance_criteria="Delete dependency test.",
        required_checklist_snapshot=[],
        actor=admin,
        reason="Dependency deletion test",
    )
    task.current_commitment = commitment
    task.current_owner = member
    task.original_owner = member
    task.committed_at = observed
    task.save()
    submission = Submission.objects.create(
        task=task,
        commitment=commitment,
        accountable_owner=member,
        submitting_actor=member,
        result_summary="Submitted before removal.",
        evidence_links=["https://example.test/remove"],
        criteria_snapshot="Delete dependency test.",
        checklist_snapshot=[],
        is_current=True,
    )
    notification = Notification.objects.create(
        semantic_key=f"delete-dependency:{task.id}",
        recipient=member,
        task=task,
        kind="due_reminder",
        scheduled_for=observed,
        status=Notification.Status.QUEUED,
    )
    slack_job = Job.objects.create(
        semantic_key=f"delete-dependency-slack:{task.id}",
        job_type="slack_delivery",
        run_after=observed,
        payload={"notification_id": str(notification.id)},
    )
    board.refresh_from_db()

    client = APIClient()
    client.force_authenticate(user=member)
    response = client.post(
        f"/api/v1/tasks/{task.id}/delete",
        {
            "expected_version": task.row_version,
            "expected_board_revision": board.revision,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="delete-committed-card-dependencies",
    )

    assert response.status_code == 200
    assert not Task.objects.filter(pk=task.id).exists()
    assert not CommitmentRevision.objects.filter(pk=commitment.id).exists()
    assert not Submission.objects.filter(pk=submission.id).exists()
    assert not Notification.objects.filter(pk=notification.id).exists()
    assert not Job.objects.filter(pk=slack_job.id).exists()


def test_monthly_recurrence_uses_business_timezone_across_utc_date_boundary():
    zone = ZoneInfo("Asia/Manila")
    utc = ZoneInfo("UTC")
    local = datetime(2027, 1, 1, 1, 30, tzinfo=zone)
    stored = local.astimezone(utc)

    advanced = _advance(stored, Task.Recurrence.MONTHLY, 1)

    assert advanced.astimezone(zone) == datetime(
        2027,
        2,
        1,
        1,
        30,
        tzinfo=zone,
    )


def test_recurring_card_can_be_committed_again_with_next_revision():
    admin, member, board = make_board()
    observed = timezone.now()
    task = create_task(
        actor=member,
        board_id=board.id,
        title="Recurring recommit",
        owner_id=member.id,
        draft_due_at=observed + timedelta(hours=1),
        draft_acceptance_criteria="First cycle completed.",
    )
    board.refresh_from_db()
    task = commit_task(
        actor=admin,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        owner_id=member.id,
        due_at=observed + timedelta(hours=1),
        acceptance_criteria="First cycle completed.",
        reason="First cycle",
    )
    task.recurrence_frequency = Task.Recurrence.DAILY
    task.recurrence_next_at = observed - timedelta(minutes=1)
    task.recurrence_anchor_day = observed.day
    task.recurrence_generation = 7
    task.save(
        update_fields=[
            "recurrence_frequency",
            "recurrence_next_at",
            "recurrence_anchor_day",
            "recurrence_generation",
        ]
    )

    assert trigger_recurrence(
        task_id=task.id,
        generation=7,
        observed_at=observed,
    )

    task.refresh_from_db()
    board.refresh_from_db()
    recommitted = commit_task(
        actor=admin,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        owner_id=member.id,
        due_at=observed + timedelta(days=1, hours=1),
        acceptance_criteria="Second cycle completed.",
        reason="Second cycle",
    )

    recommitted.refresh_from_db()
    revisions = list(
        CommitmentRevision.objects.filter(task=recommitted)
        .order_by("revision")
        .values_list("revision", flat=True)
    )
    assert revisions == [1, 2]
    assert recommitted.current_commitment is not None
    assert recommitted.current_commitment.revision == 2


def test_scheduler_prunes_expired_database_sessions():
    observed = timezone.now()
    Session.objects.create(
        session_key="expired-session-row",
        session_data="",
        expire_date=observed - timedelta(minutes=1),
    )
    Session.objects.create(
        session_key="active-session-row",
        session_data="",
        expire_date=observed + timedelta(days=1),
    )

    result = scheduler_tick()

    assert not Session.objects.filter(session_key="expired-session-row").exists()
    assert Session.objects.filter(session_key="active-session-row").exists()
    assert result["expired_sessions_pruned"] >= 1


def test_archived_repeating_card_does_not_reactivate():
    _, member, board = make_board()
    task = create_task(actor=member, board_id=board.id, title="Archived repeat")
    next_at = timezone.now() + timedelta(hours=1)
    configure_recurrence(
        task,
        frequency=Task.Recurrence.DAILY,
        next_at=next_at,
    )
    task.save(
        update_fields=[
            "recurrence_frequency",
            "recurrence_next_at",
            "recurrence_anchor_day",
            "recurrence_generation",
            "updated_at",
        ]
    )

    task.is_archived = True
    task.archived_at = timezone.now()
    task.recurrence_generation += 1
    task.save(
        update_fields=[
            "is_archived",
            "archived_at",
            "recurrence_generation",
            "updated_at",
        ]
    )

    triggered = trigger_recurrence(
        task_id=task.id,
        generation=task.recurrence_generation,
        observed_at=next_at + timedelta(minutes=1),
    )

    task.refresh_from_db()
    assert triggered is False
    assert task.is_archived is True
    assert task.column.state == BoardColumn.State.BACKLOG
