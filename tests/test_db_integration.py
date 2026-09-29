from __future__ import annotations

import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from boards.models import Board, BoardColumn, BoardMembership
from core.idempotency import IdempotencyError, run_idempotent
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.utils import timezone
from notifications import jobs
from notifications.models import Job, Notification
from notifications.policy import create_task_notification
from notifications.worker import worker_tick
from reports.services import create_snapshot
from schedules.generation import generate_schedule_batch
from schedules.models import Occurrence, Schedule, ScheduleRevision
from workitems.errors import DomainError
from workitems.models import ChangeProposal, ChecklistItem, CommentEditHistory, Review, Task
from workitems.services import (
    add_comment,
    cancel_task,
    commit_task,
    correct_comment,
    create_task,
    move_task,
    propose_change,
    reopen_task,
    resolve_change_proposal,
    review_submission,
    revise_commitment,
    set_checklist_item,
    submit_result,
)

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


def make_board():
    admin = User.objects.create_user(username="admin", password=None, is_staff=True)
    manager = User.objects.create_user(username="manager", password=None)
    reviewer = User.objects.create_user(username="reviewer", password=None)
    member = User.objects.create_user(username="member", password=None)
    outsider = User.objects.create_user(username="outsider", password=None)
    board = Board.objects.create(name="Ops", created_by=admin)
    for position, (state, label) in enumerate(STANDARD_COLUMNS):
        BoardColumn.objects.create(board=board, state=state, name=label, position=position)
    for user, role in (
        (manager, BoardMembership.Role.MANAGER),
        (reviewer, BoardMembership.Role.MANAGER),
        (member, BoardMembership.Role.MEMBER),
    ):
        BoardMembership.objects.create(
            board=board,
            user=user,
            role=role,
            created_by=admin,
        )
    return admin, manager, reviewer, member, outsider, board


def future_due(hours: int = 2) -> datetime:
    return timezone.now() + timedelta(hours=hours)


def create_committed_task(manager, member, board):
    due = future_due()
    task = create_task(
        actor=member,
        board_id=board.id,
        title="Close daily reconciliation",
        priority=3,
        owner_id=member.id,
        draft_due_at=due,
        draft_acceptance_criteria="Reconciliation is complete with evidence attached.",
    )
    board.refresh_from_db()
    task = commit_task(
        actor=manager,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        owner_id=member.id,
        due_at=due,
        acceptance_criteria="Reconciliation is complete with evidence attached.",
        reason="Approved commitment",
    )
    board.refresh_from_db()
    task.refresh_from_db()
    return task


def test_member_cannot_commit_but_manager_can_and_jobs_are_created():
    _, manager, _, member, _, board = make_board()
    due = future_due()
    task = create_task(
        actor=member,
        board_id=board.id,
        title="Priority task",
        priority=3,
        owner_id=member.id,
        draft_due_at=due,
        draft_acceptance_criteria="Evidence uploaded.",
    )
    board.refresh_from_db()

    with pytest.raises(PermissionDenied):
        commit_task(
            actor=member,
            task_id=task.id,
            expected_version=task.row_version,
            expected_board_revision=board.revision,
            owner_id=member.id,
            due_at=due,
            acceptance_criteria="Evidence uploaded.",
        )

    task = commit_task(
        actor=manager,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        owner_id=member.id,
        due_at=due,
        acceptance_criteria="Evidence uploaded.",
        reason="Manager approved",
    )
    task.refresh_from_db()
    assert task.column.state == BoardColumn.State.TODO
    assert task.original_owner_id == member.id
    assert task.current_commitment is not None
    assert Job.objects.filter(job_type="assignment_notification").exists()
    assert Job.objects.filter(job_type="overdue_escalation").exists()


def test_submit_and_independent_review_reaches_done_and_self_review_is_blocked():
    _, manager, reviewer, member, _, board = make_board()
    task = create_committed_task(manager, member, board)

    task = submit_result(
        actor=manager,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        result_summary="Completed and reconciled.",
        evidence_links=["https://example.test/evidence/1"],
    )
    board.refresh_from_db()
    task.refresh_from_db()
    assert task.column.state == BoardColumn.State.TODO
    assert Job.objects.filter(job_type="review_request").exists()

    with pytest.raises(DomainError, match="independent"):
        review_submission(
            actor=manager,
            task_id=task.id,
            expected_version=task.row_version,
            expected_board_revision=board.revision,
            decision=Review.Decision.ACCEPTED,
        )

    task = review_submission(
        actor=reviewer,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        decision=Review.Decision.ACCEPTED,
        feedback="Evidence verified.",
    )
    task.refresh_from_db()
    assert task.column.state == BoardColumn.State.DONE
    assert task.submissions.get(is_current=True).review.decision == Review.Decision.ACCEPTED


def test_stale_version_is_rejected():
    _, manager, _, member, _, board = make_board()
    task = create_committed_task(manager, member, board)
    board.refresh_from_db()
    task.refresh_from_db()

    with pytest.raises(DomainError) as caught:
        submit_result(
            actor=member,
            task_id=task.id,
            expected_version=task.row_version - 1,
            expected_board_revision=board.revision,
            result_summary="Completed.",
            evidence_links=["https://example.test/evidence/stale"],
        )
    assert caught.value.code == "stale_state"
    assert caught.value.status == 409


def test_idempotency_replays_same_payload_and_rejects_key_reuse_with_different_payload():
    admin, _, _, _, _, _ = make_board()
    calls = {"count": 0}

    def handler():
        calls["count"] += 1
        return 201, {"created": True, "sequence": calls["count"]}

    first = run_idempotent(
        actor=admin,
        endpoint="/api/v1/example",
        key="stable-key",
        payload={"value": 1},
        handler=handler,
    )
    second = run_idempotent(
        actor=admin,
        endpoint="/api/v1/example",
        key="stable-key",
        payload={"value": 1},
        handler=handler,
    )

    assert first.replayed is False
    assert second.replayed is True
    assert first.body == second.body
    assert calls["count"] == 1

    with pytest.raises(IdempotencyError) as caught:
        run_idempotent(
            actor=admin,
            endpoint="/api/v1/example",
            key="stable-key",
            payload={"value": 2},
            handler=handler,
        )
    assert caught.value.code == "idempotency_mismatch"
    assert caught.value.status == 409


def test_recurrence_creates_one_occurrence_per_period_and_is_idempotent():
    _, manager, _, member, _, board = make_board()
    zone = ZoneInfo("Asia/Manila")
    local_today = timezone.now().astimezone(zone).date()
    rule = {
        "frequency": "daily",
        "interval": 1,
        "anchor_date": local_today.isoformat(),
        "timezone": "Asia/Manila",
        "release_time": "00:01",
        "due_time": "23:59",
        "workdays_iso": [1, 2, 3, 4, 5, 6, 7],
        "holidays": [],
        "shift_policy": "none",
    }
    schedule = Schedule.objects.create(
        board=board,
        name="Daily close",
        timezone="Asia/Manila",
        active=True,
        generation=1,
        created_by=manager,
    )
    revision = ScheduleRevision.objects.create(
        schedule=schedule,
        revision=1,
        rule=rule,
        template_fields={
            "title": "Daily close",
            "description": "",
            "priority": 2,
            "owner_id": str(member.id),
            "acceptance_criteria": "Daily close completed.",
            "required_checklist": [],
        },
        effective_base_period=local_today.isoformat(),
        actor=manager,
        reason="Initial schedule",
    )
    schedule.current_revision = revision
    schedule.save(update_fields=["current_revision"])

    first = generate_schedule_batch(schedule.id)
    second = generate_schedule_batch(schedule.id)

    assert len(first["created"]) == 1
    assert second["created"] == []
    assert Occurrence.objects.filter(schedule=schedule).count() == 1
    occurrence = Occurrence.objects.get(schedule=schedule)
    assert occurrence.period_key == local_today.isoformat()
    assert occurrence.task.current_commitment is not None


def test_report_snapshot_uses_accepted_submission_and_is_immutable_data():
    _, manager, reviewer, member, _, board = make_board()
    task = create_committed_task(manager, member, board)

    task = submit_result(
        actor=member,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        result_summary="Completed with evidence.",
        evidence_links=["https://example.test/evidence/report"],
    )
    board.refresh_from_db()
    task = review_submission(
        actor=reviewer,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        decision=Review.Decision.ACCEPTED,
        feedback="Accepted",
    )

    report_date = timezone.now().astimezone(ZoneInfo("Asia/Manila")).date()
    snapshot = create_snapshot(recipient=reviewer, report_date=report_date)

    assert snapshot is not None
    assert snapshot.definition_version >= 1
    assert snapshot.metrics["accepted_results"] >= 1
    row = next(item for item in snapshot.rows if item["task_id"] == str(task.id))
    assert row["result_summary"] == "Completed with evidence."
    assert row["original_category"] in {"early", "on_time", "late"}


def test_expired_job_recovery_distinguishes_internal_and_ambiguous_send_boundaries():
    observed = timezone.now()
    leased = Job.objects.create(
        semantic_key="expired-leased",
        job_type="test",
        run_after=observed - timedelta(minutes=2),
        status=Job.Status.LEASED,
        lease_token=__import__("uuid").uuid4(),
        lease_expires_at=observed - timedelta(minutes=1),
        payload={},
    )
    sending = Job.objects.create(
        semantic_key="expired-sending",
        job_type="slack_delivery",
        run_after=observed - timedelta(minutes=2),
        status=Job.Status.SENDING,
        lease_token=__import__("uuid").uuid4(),
        lease_expires_at=observed - timedelta(minutes=1),
        payload={},
    )

    result = jobs.recover_expired_leases()
    leased.refresh_from_db()
    sending.refresh_from_db()

    assert result == {"unknown": 1, "requeued": 1}
    assert leased.status == Job.Status.READY
    assert leased.last_error_code == "expired_internal_lease"
    assert sending.status == Job.Status.UNKNOWN
    assert sending.last_error_code == "expired_sending_lease"


def test_worker_creates_in_app_assignment_notification_without_slack_job():
    _, manager, _, member, _, board = make_board()
    task = create_committed_task(manager, member, board)
    assignment = Job.objects.get(job_type="assignment_notification", payload__task_id=str(task.id))
    assignment.run_after = timezone.now() - timedelta(seconds=1)
    assignment.save(update_fields=["run_after"])

    result = worker_tick()
    assignment.refresh_from_db()

    assert result["processed"] >= 1
    assert assignment.status == Job.Status.SUCCEEDED
    notification = Notification.objects.get(semantic_key=assignment.semantic_key)
    assert notification.recipient_id == member.id
    assert notification.kind == "assignment_notification"
    assert notification.status == Notification.Status.QUEUED
    assert not Job.objects.filter(job_type="slack_delivery").exists()


def test_commitment_revision_preserves_original_baseline_and_updates_current_values():
    _, manager, _, member, _, board = make_board()
    task = create_committed_task(manager, member, board)
    original = task.current_commitment
    assert original is not None
    original_due = original.due_at

    revised_due = original_due + timedelta(hours=3)
    board.refresh_from_db()
    task.refresh_from_db()
    task = revise_commitment(
        actor=manager,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        reason="Scope changed",
        due_at=revised_due,
        priority=2,
        acceptance_criteria="Revised measurable acceptance criteria.",
    )
    task.refresh_from_db()
    revisions = list(task.commitments.order_by("revision"))

    assert [item.revision for item in revisions] == [1, 2]
    assert revisions[0].due_at == original_due
    assert revisions[1].due_at == revised_due
    assert task.current_commitment_id == revisions[1].id
    assert task.priority == 2


def test_change_proposal_acceptance_creates_commitment_revision():
    _, manager, _, member, _, board = make_board()
    task = create_committed_task(manager, member, board)

    proposal = propose_change(
        actor=member,
        task_id=task.id,
        proposed_changes={"priority": 2},
        reason="Lower urgency after dependency cleared.",
    )
    task.refresh_from_db()
    board.refresh_from_db()

    task = resolve_change_proposal(
        actor=manager,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        proposal_id=proposal.id,
        decision=ChangeProposal.Status.ACCEPTED,
        reason="Approved by manager.",
    )
    proposal.refresh_from_db()
    task.refresh_from_db()

    assert proposal.status == ChangeProposal.Status.ACCEPTED
    assert task.current_commitment is not None
    assert task.current_commitment.revision == 2
    assert task.priority == 2


def test_comment_correction_retains_edit_history():
    _, manager, _, member, _, board = make_board()
    task = create_committed_task(manager, member, board)
    board.refresh_from_db()
    task.refresh_from_db()

    task = add_comment(
        actor=member,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        body="Initial note.",
    )
    comment = task.comments.get()
    board.refresh_from_db()
    task.refresh_from_db()

    task = correct_comment(
        actor=member,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        comment_id=comment.id,
        body="Corrected note.",
    )
    comment.refresh_from_db()
    history = CommentEditHistory.objects.get(comment=comment)

    assert comment.body == "Corrected note."
    assert comment.corrected_at is not None
    assert history.previous_body == "Initial note."
    assert history.replacement_body == "Corrected note."


def test_concurrent_moves_use_real_database_locks_and_reject_stale_writer():
    _, manager, _, member, _, board = make_board()
    task = create_committed_task(manager, member, board)
    task.refresh_from_db()
    board.refresh_from_db()
    expected_version = task.row_version
    expected_board_revision = board.revision
    barrier = threading.Barrier(2)
    results: list[tuple[str, str]] = []
    result_lock = threading.Lock()

    def attempt(target_state: str, reason: str) -> None:
        close_old_connections()
        try:
            actor = User.objects.get(pk=member.pk)
            barrier.wait(timeout=5)
            move_task(
                actor=actor,
                task_id=task.id,
                target_state=target_state,
                target_position=0,
                expected_version=expected_version,
                expected_board_revision=expected_board_revision,
                reason=reason,
            )
            outcome = ("ok", target_state)
        except DomainError as exc:
            outcome = (exc.code, target_state)
        finally:
            close_old_connections()
        with result_lock:
            results.append(outcome)

    first = threading.Thread(
        target=attempt,
        args=(BoardColumn.State.IN_PROGRESS, ""),
        daemon=True,
    )
    second = threading.Thread(
        target=attempt,
        args=(BoardColumn.State.BLOCKED, "Waiting for dependency"),
        daemon=True,
    )
    first.start()
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)

    assert not first.is_alive()
    assert not second.is_alive()
    assert sorted(item[0] for item in results) == ["ok", "stale_state"]

    task.refresh_from_db()
    board.refresh_from_db()
    assert task.row_version == expected_version + 1
    assert board.revision == expected_board_revision + 1
    assert task.column.state in {BoardColumn.State.IN_PROGRESS, BoardColumn.State.BLOCKED}
    positions = list(
        Task.objects.filter(column=task.column, is_cancelled=False).values_list(
            "position", flat=True
        )
    )
    assert len(positions) == len(set(positions))


def test_done_task_can_be_reopened_then_cancelled_with_history_preserved():
    _, manager, reviewer, member, _, board = make_board()
    task = create_committed_task(manager, member, board)
    task = submit_result(
        actor=member,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        result_summary="Completed before reopening.",
        evidence_links=["https://example.test/evidence/reopen"],
    )
    board.refresh_from_db()
    task = review_submission(
        actor=reviewer,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        decision=Review.Decision.ACCEPTED,
        feedback="Accepted before scope reopened.",
    )
    board.refresh_from_db()
    task.refresh_from_db()
    accepted_submission = task.submissions.get(is_current=True)
    assert task.column.state == BoardColumn.State.DONE

    task = reopen_task(
        actor=manager,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        reason="Additional work required.",
    )
    task.refresh_from_db()
    board.refresh_from_db()
    accepted_submission.refresh_from_db()
    assert task.column.state == BoardColumn.State.IN_PROGRESS
    assert accepted_submission.is_current is False

    task = cancel_task(
        actor=manager,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        reason="Work superseded by a replacement process.",
    )
    task.refresh_from_db()
    assert task.is_cancelled is True
    assert task.cancelled_reason == "Work superseded by a replacement process."
    assert task.submissions.filter(pk=accepted_submission.pk).exists()
    assert task.audit_events.filter(action="reopen_task").exists()
    assert task.audit_events.filter(action="cancel_task").exists()


def test_old_assignment_notification_is_suppressed_after_commitment_revision():
    _, manager, _, member, _, board = make_board()
    task = create_committed_task(manager, member, board)
    old_job = Job.objects.get(
        job_type="assignment_notification",
        payload__task_id=str(task.id),
    )
    old_commitment_id = str(task.current_commitment_id)
    task.refresh_from_db()
    board.refresh_from_db()

    task = revise_commitment(
        actor=manager,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        reason="Deadline moved",
        due_at=task.current_commitment.due_at + timedelta(hours=1),
    )
    task.refresh_from_db()

    assert str(task.current_commitment_id) != old_commitment_id
    assert create_task_notification(old_job) is None


def test_assignment_notification_is_suppressed_after_task_is_done():
    _, manager, reviewer, member, _, board = make_board()
    task = create_committed_task(manager, member, board)
    assignment = Job.objects.get(
        job_type="assignment_notification",
        payload__task_id=str(task.id),
    )
    task = submit_result(
        actor=member,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        result_summary="Done before assignment send.",
        evidence_links=["https://example.test/evidence/done-before-send"],
    )
    board.refresh_from_db()
    task = review_submission(
        actor=reviewer,
        task_id=task.id,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        decision=Review.Decision.ACCEPTED,
    )
    task.refresh_from_db()

    assert task.column.state == BoardColumn.State.DONE
    assert create_task_notification(assignment) is None


def test_uncommitted_card_can_move_freely_across_trello_lists():
    _, _, _, member, _, board = make_board()
    task = create_task(
        actor=member,
        board_id=board.id,
        title="Flexible card",
        priority=1,
        owner_id=None,
    )

    for target_state in (
        BoardColumn.State.TODO,
        BoardColumn.State.IN_PROGRESS,
        BoardColumn.State.BLOCKED,
        BoardColumn.State.DONE,
        BoardColumn.State.BACKLOG,
    ):
        board.refresh_from_db()
        task.refresh_from_db()
        task = move_task(
            actor=member,
            task_id=task.id,
            target_state=target_state,
            target_position=None,
            expected_version=task.row_version,
            expected_board_revision=board.revision,
            reason="Drag test",
        )
        task.refresh_from_db()
        assert task.column.state == target_state


def test_checklist_remains_editable_after_card_is_dragged_to_done():
    _, _, _, member, _, board = make_board()
    task = create_task(
        actor=member,
        board_id=board.id,
        title="Done card remains editable",
        priority=1,
        owner_id=None,
    )
    item = ChecklistItem.objects.create(
        task=task,
        text="Final follow-up",
        required=False,
        position=0,
        checked=False,
    )

    board.refresh_from_db()
    task.refresh_from_db()
    task = move_task(
        actor=member,
        task_id=task.id,
        target_state=BoardColumn.State.DONE,
        target_position=None,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
        reason="Finished for now",
    )

    board.refresh_from_db()
    task.refresh_from_db()
    updated = set_checklist_item(
        actor=member,
        task_id=task.id,
        item_id=item.id,
        checked=True,
        expected_version=task.row_version,
        expected_board_revision=board.revision,
    )

    item.refresh_from_db()
    updated.refresh_from_db()
    assert updated.column.state == BoardColumn.State.DONE
    assert item.checked is True
