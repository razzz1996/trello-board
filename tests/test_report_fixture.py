from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from boards.models import Board, BoardColumn, BoardMembership
from core.clock import use_clock
from django.contrib.auth import get_user_model
from reports.services import calculate_report, create_snapshot
from workitems.models import Review
from workitems.services import (
    cancel_task,
    commit_task,
    create_task,
    move_task,
    reopen_task,
    review_submission,
    revise_commitment,
    submit_result,
)

from tests.clock_fixtures import FrozenClock

User = get_user_model()
MANILA = ZoneInfo("Asia/Manila")
pytestmark = pytest.mark.django_db(transaction=True)

STANDARD_COLUMNS = [
    (BoardColumn.State.BACKLOG, "Backlog"),
    (BoardColumn.State.TODO, "To Do"),
    (BoardColumn.State.IN_PROGRESS, "In Progress"),
    (BoardColumn.State.BLOCKED, "Blocked"),
    (BoardColumn.State.REVIEW, "Review"),
    (BoardColumn.State.DONE, "Done"),
]


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 29, hour, minute, tzinfo=MANILA)


def setup_board(prefix: str = "report"):
    admin = User.objects.create_user(username=f"{prefix}-admin", password=None, is_staff=True)
    manager = User.objects.create_user(username=f"{prefix}-manager", password=None)
    reviewer = User.objects.create_user(username=f"{prefix}-reviewer", password=None)
    member = User.objects.create_user(username=f"{prefix}-member", password=None)
    board = Board.objects.create(name=f"{prefix} board", created_by=admin)
    for position, (state, label) in enumerate(STANDARD_COLUMNS):
        BoardColumn.objects.create(board=board, state=state, name=label, position=position)
    for user in (manager, reviewer):
        BoardMembership.objects.create(
            board=board,
            user=user,
            role=BoardMembership.Role.MANAGER,
            created_by=admin,
        )
    BoardMembership.objects.create(
        board=board,
        user=member,
        role=BoardMembership.Role.MEMBER,
        created_by=admin,
    )
    return admin, manager, reviewer, member, board


def committed_task(title: str, manager, member, board, *, due: datetime | None = None):
    due = due or at(17)
    with use_clock(FrozenClock(at(9))):
        task = create_task(
            actor=member,
            board_id=board.id,
            title=title,
            priority=2,
            owner_id=member.id,
            draft_due_at=due,
            draft_acceptance_criteria=f"{title} accepted result.",
        )
        board.refresh_from_db()
        task = commit_task(
            actor=manager,
            task_id=task.id,
            expected_version=task.row_version,
            expected_board_revision=board.revision,
            owner_id=member.id,
            due_at=due,
            acceptance_criteria=f"{title} accepted result.",
            reason="Deterministic report fixture",
        )
    board.refresh_from_db()
    task.refresh_from_db()
    return task


def accept_at(task, board, member, reviewer, submitted_at: datetime):
    with use_clock(FrozenClock(submitted_at)):
        task = submit_result(
            actor=member,
            task_id=task.id,
            expected_version=task.row_version,
            expected_board_revision=board.revision,
            result_summary=f"Accepted result for {task.title}",
            evidence_links=[f"https://example.test/{task.title.lower()}"],
        )
    board.refresh_from_db()
    task.refresh_from_db()
    with use_clock(FrozenClock(submitted_at + timedelta(minutes=1))):
        task = review_submission(
            actor=reviewer,
            task_id=task.id,
            expected_version=task.row_version,
            expected_board_revision=board.revision,
            decision=Review.Decision.ACCEPTED,
            feedback="Fixture acceptance",
        )
    board.refresh_from_db()
    task.refresh_from_db()
    return task


def build_main_fixture(prefix: str = "fixture"):
    _, manager, reviewer, member, board = setup_board(prefix)
    tasks = {name: committed_task(name, manager, member, board) for name in "ABCDEFGHI"}

    for name, submitted in {
        "A": at(15),
        "B": at(16),
        "C": at(16, 30),
        "D": at(17),
        "E": at(17, 1),
    }.items():
        tasks[name] = accept_at(tasks[name], board, member, reviewer, submitted)

    with use_clock(FrozenClock(at(16))):
        task_f = tasks["F"]
        tasks["F"] = submit_result(
            actor=member,
            task_id=task_f.id,
            expected_version=task_f.row_version,
            expected_board_revision=board.revision,
            result_summary="Pending F",
            evidence_links=["https://example.test/f"],
        )
    board.refresh_from_db()
    tasks["F"].refresh_from_db()

    tasks["G"] = move_task(
        actor=member,
        task_id=tasks["G"].id,
        target_state=BoardColumn.State.IN_PROGRESS,
        target_position=0,
        expected_version=tasks["G"].row_version,
        expected_board_revision=board.revision,
    )
    board.refresh_from_db()
    tasks["H"] = move_task(
        actor=member,
        task_id=tasks["H"].id,
        target_state=BoardColumn.State.BLOCKED,
        target_position=0,
        expected_version=tasks["H"].row_version,
        expected_board_revision=board.revision,
        reason="Fixture blocker",
    )
    board.refresh_from_db()
    tasks["I"] = cancel_task(
        actor=manager,
        task_id=tasks["I"].id,
        expected_version=tasks["I"].row_version,
        expected_board_revision=board.revision,
        reason="Fixture cancellation",
    )
    board.refresh_from_db()
    return manager, reviewer, member, board, tasks


def report(reviewer, observed_at: datetime | None = None):
    observed_at = observed_at or at(17, 30)
    with use_clock(FrozenClock(observed_at)):
        return calculate_report(
            recipient=reviewer,
            report_date=observed_at.date(),
            observed_at=observed_at,
        )


def test_main_nine_task_fixture_matches_exact_runbook_arithmetic():
    _, reviewer, _, _, _ = build_main_fixture("main")
    rows, metrics = report(reviewer)

    assert len(rows) == 9
    assert metrics["net_cohort"] == 8
    assert metrics["gross_cohort"] == 9
    assert metrics["early"] == 2
    assert metrics["on_time"] == 2
    assert metrics["late"] == 1
    assert metrics["pending_review"] == 1
    assert metrics["unfinished"] == 2
    assert metrics["accepted_results"] == 5
    assert metrics["cancelled"] == 1
    assert metrics["original_deadline_adherence_percent"] == "50.00"
    assert metrics["gross_commitment_adherence_percent"] == "44.44"
    assert metrics["provisional"] is True
    by_title = {row["title"]: row for row in rows}
    assert by_title["H"]["overdue"] is True
    assert by_title["H"]["blocked"] is True
    assert by_title["F"]["pending_review"] is True
    assert by_title["F"]["overdue"] is False


def test_mutation_1_approve_pending_f_uses_original_submission_and_preserves_saved_snapshot():
    _, reviewer, member, board, tasks = build_main_fixture("mutation1")
    with use_clock(FrozenClock(at(17, 30))):
        saved = create_snapshot(recipient=reviewer, report_date=at(17, 30).date())
    assert saved is not None
    assert saved.metrics["original_deadline_adherence_percent"] == "50.00"

    task_f = tasks["F"]
    with use_clock(FrozenClock(at(18))):
        task_f = review_submission(
            actor=reviewer,
            task_id=task_f.id,
            expected_version=task_f.row_version,
            expected_board_revision=board.revision,
            decision=Review.Decision.ACCEPTED,
        )
    board.refresh_from_db()
    rows, metrics = report(reviewer, at(18))
    row_f = next(row for row in rows if row["title"] == "F")

    assert row_f["accepted_submission_at"].endswith("08:00:00+00:00")
    assert row_f["original_category"] == "early"
    assert metrics["original_deadline_adherence_percent"] == "62.50"
    saved.refresh_from_db()
    assert saved.metrics["original_deadline_adherence_percent"] == "50.00"


def test_mutation_2_rejected_f_resubmitted_at_18_is_late():
    _, reviewer, member, board, tasks = build_main_fixture("mutation2")
    task_f = tasks["F"]
    with use_clock(FrozenClock(at(17, 45))):
        task_f = review_submission(
            actor=reviewer,
            task_id=task_f.id,
            expected_version=task_f.row_version,
            expected_board_revision=board.revision,
            decision=Review.Decision.REJECTED,
            feedback="Rework",
        )
    board.refresh_from_db()
    task_f.refresh_from_db()
    with use_clock(FrozenClock(at(18))):
        task_f = submit_result(
            actor=member,
            task_id=task_f.id,
            expected_version=task_f.row_version,
            expected_board_revision=board.revision,
            result_summary="F resubmitted",
            evidence_links=["https://example.test/f-late"],
        )
    board.refresh_from_db()
    task_f.refresh_from_db()
    with use_clock(FrozenClock(at(18, 1))):
        review_submission(
            actor=reviewer,
            task_id=task_f.id,
            expected_version=task_f.row_version,
            expected_board_revision=board.revision,
            decision=Review.Decision.ACCEPTED,
        )
    rows, _ = report(reviewer, at(18, 5))
    row_f = next(row for row in rows if row["title"] == "F")
    assert row_f["original_category"] == "late"
    assert row_f["accepted_submission_at"].endswith("10:00:00+00:00")


def test_mutation_3_revised_e_deadline_changes_only_revised_category():
    manager, reviewer, _, board, tasks = build_main_fixture("mutation3")
    task_e = tasks["E"]
    task_e.refresh_from_db()
    board.refresh_from_db()
    with use_clock(FrozenClock(at(17, 15))):
        revise_commitment(
            actor=manager,
            task_id=task_e.id,
            expected_version=task_e.row_version,
            expected_board_revision=board.revision,
            reason="Approved revised deadline",
            due_at=at(18),
        )
    rows, _ = report(reviewer)
    row_e = next(row for row in rows if row["title"] == "E")
    assert row_e["original_category"] == "late"
    assert row_e["revised_category"] == "on_time"


def test_mutation_4_reopen_a_removes_current_credit_but_saved_snapshot_stays_unchanged():
    manager, reviewer, _, board, tasks = build_main_fixture("mutation4")
    with use_clock(FrozenClock(at(17, 30))):
        saved = create_snapshot(recipient=reviewer, report_date=at(17, 30).date())
    assert saved is not None
    task_a = tasks["A"]
    board.refresh_from_db()
    with use_clock(FrozenClock(at(17, 40))):
        reopen_task(
            actor=manager,
            task_id=task_a.id,
            expected_version=task_a.row_version,
            expected_board_revision=board.revision,
            reason="Additional scope",
        )
    rows, metrics = report(reviewer, at(17, 45))
    row_a = next(row for row in rows if row["title"] == "A")
    assert row_a["reopened"] is True
    assert row_a["original_category"] is None
    assert metrics["accepted_results"] == 4
    saved.refresh_from_db()
    assert saved.metrics["accepted_results"] == 5


def test_mutation_5_future_j_expands_full_cohort_not_matured_cohort():
    manager, reviewer, member, board, _ = build_main_fixture("mutation5")
    committed_task("J", manager, member, board, due=at(19))
    _, metrics = report(reviewer)
    assert metrics["net_cohort"] == 9
    assert metrics["matured_cohort"] == 8
    assert metrics["upcoming"] == 1


def test_mutation_6_zero_denominator_is_na_not_zero_or_error():
    _, _, reviewer, _, _ = setup_board("mutation6")
    rows, metrics = report(reviewer)
    assert rows == []
    assert metrics["net_cohort"] == 0
    assert metrics["original_deadline_adherence_percent"] is None
    assert metrics["gross_commitment_adherence_percent"] is None


def test_mutation_7_unauthorized_second_board_does_not_change_counts():
    manager, reviewer, _, _, _ = build_main_fixture("mutation7-main")
    _, baseline = report(reviewer)

    _, other_manager, _, other_member, other_board = setup_board("mutation7-other")
    for name in "ABCDEFGHI":
        committed_task(f"other-{name}", other_manager, other_member, other_board)

    _, after = report(reviewer)
    assert after["net_cohort"] == baseline["net_cohort"] == 8
    assert after["gross_cohort"] == baseline["gross_cohort"] == 9
    assert manager.id != other_manager.id


def test_delayed_snapshot_records_actual_observation_without_backdating():
    _, reviewer, _, _, _ = build_main_fixture("delayed")
    observed = at(18, 5)
    with use_clock(FrozenClock(observed)):
        snapshot = create_snapshot(
            recipient=reviewer,
            report_date=observed.date(),
        )

    assert snapshot is not None
    assert snapshot.scheduled_for == at(17, 30)
    assert snapshot.observation_started_at == observed
    assert snapshot.generated_at == observed
    assert snapshot.delayed is True
