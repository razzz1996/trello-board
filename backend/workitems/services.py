from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from boards.models import Board, BoardColumn, BoardMembership
from boards.permissions import require_board_manager, require_board_member
from core.clock import now
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .errors import DomainError
from .models import (
    AuditEvent,
    ChangeProposal,
    ChecklistItem,
    Comment,
    CommentEditHistory,
    CommitmentRevision,
    Review,
    Submission,
    Task,
)
from .recurrence import configure_recurrence

User = get_user_model()
TEMP_POSITION_OFFSET = 1_000_000
MOVING_TEMP_POSITION = 2_000_000


def _serialize_task(task: Task) -> dict[str, Any]:
    commitment = task.current_commitment
    return {
        "id": str(task.id),
        "board_id": str(task.board_id),
        "column_id": str(task.column_id),
        "title": task.title,
        "priority": task.priority,
        "owner_id": str(task.current_owner_id) if task.current_owner_id else None,
        "row_version": task.row_version,
        "position": task.position,
        "is_cancelled": task.is_cancelled,
        "commitment_revision": commitment.revision if commitment else None,
        "due_at": commitment.due_at.isoformat() if commitment else None,
        "recurrence_frequency": task.recurrence_frequency,
        "recurrence_next_at": (
            task.recurrence_next_at.isoformat() if task.recurrence_next_at else None
        ),
        "recurrence_generation": task.recurrence_generation,
    }


def _require_expected(
    task: Task, board: Board, expected_version: int, expected_board_revision: int
) -> None:
    if task.row_version != expected_version or board.revision != expected_board_revision:
        raise DomainError(
            "stale_state",
            "The task or board changed since it was loaded.",
            status=409,
            field_errors={
                "expected_version": task.row_version,
                "expected_board_revision": board.revision,
            },
        )


def _board_and_task_for_update(task_id) -> tuple[Board, Task]:
    board_id = Task.objects.filter(pk=task_id).values_list("board_id", flat=True).first()
    if board_id is None:
        raise DomainError("not_found", "Task not found.", status=404)
    board = Board.objects.select_for_update().get(pk=board_id)
    task = (
        Task.objects.select_for_update(of=("self",))
        .select_related("column", "current_commitment", "current_owner")
        .filter(
            pk=task_id,
            board=board,
            is_archived=False,
            column__is_archived=False,
        )
        .first()
    )
    if task is None:
        raise DomainError("not_found", "Task not found.", status=404)
    return board, task


def _eligible_owner(board: Board, owner_id) -> Any:
    user = User.objects.filter(pk=owner_id, is_active=True).first()
    if user is None:
        raise DomainError(
            "invalid_owner",
            "Owner must be an active user.",
            field_errors={"owner_id": ["Invalid owner."]},
        )
    return user


def _column(board: Board, state: str) -> BoardColumn:
    try:
        return BoardColumn.objects.get(board=board, state=state, is_archived=False)
    except BoardColumn.DoesNotExist as exc:
        raise DomainError(
            "invalid_board", f"Board is missing the {state} column.", status=409
        ) from exc


def _column_by_id(board: Board, column_id) -> BoardColumn:
    try:
        column = BoardColumn.objects.filter(board=board, pk=column_id).first()
    except (TypeError, ValueError):
        column = None
    if column is None or column.state == BoardColumn.State.REVIEW or column.is_archived:
        raise DomainError("invalid_column", "Target list does not exist on this board.", status=409)
    return column


def _next_position(column: BoardColumn) -> int:
    current = (
        Task.objects.filter(column=column, is_cancelled=False, is_archived=False)
        .aggregate(value=Max("position"))
        .get("value")
    )
    return 0 if current is None else int(current) + 1


def _bump(board: Board, task: Task) -> None:
    board.revision += 1
    task.row_version += 1
    board.save(update_fields=["revision", "updated_at"])
    task.save(update_fields=["row_version", "updated_at"])


def _audit(
    board: Board,
    task: Task,
    actor,
    action: str,
    *,
    reason: str = "",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    AuditEvent.objects.create(
        board=board,
        board_revision=board.revision,
        task=task,
        actor=actor,
        action=action,
        reason=reason,
        before=before or {},
        after=after or {},
    )


def _validate_due(value: datetime) -> None:
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise DomainError(
            "invalid_due_time",
            "Deadline must be a timezone-aware datetime.",
            field_errors={"due_at": ["A timezone offset is required."]},
        )


def _validate_evidence_links(links: Iterable[str]) -> list[str]:
    clean: list[str] = []
    for value in links:
        if not isinstance(value, str) or len(value) > 2000:
            raise DomainError("invalid_evidence", "Evidence links must be valid URLs.")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise DomainError("invalid_evidence", "Evidence links must use http or https.")
        if parsed.username or parsed.password:
            raise DomainError(
                "invalid_evidence", "Evidence links cannot contain embedded credentials."
            )
        clean.append(value)
    if not clean:
        raise DomainError("missing_evidence", "At least one evidence link is required.")
    return clean


def _required_checklist_snapshot(task: Task) -> list[dict[str, Any]]:
    return [
        {"id": str(item.id), "text": item.text, "required": item.required}
        for item in task.checklist_items.filter(required=True).order_by("position")
    ]


def _resequence_for_move(task: Task, target: BoardColumn, target_position: int | None) -> None:
    source_id = task.column_id
    target_id = target.id
    column_ids = {source_id, target_id}
    locked = list(
        Task.objects.select_for_update()
        .filter(
            column_id__in=column_ids,
            is_cancelled=False,
            is_archived=False,
        )
        .order_by("column_id", "position", "id")
    )
    source_items = [item for item in locked if item.column_id == source_id and item.id != task.id]
    if source_id == target_id:
        target_items = source_items
    else:
        target_items = [
            item for item in locked if item.column_id == target_id and item.id != task.id
        ]

    index = (
        len(target_items)
        if target_position is None
        else max(0, min(int(target_position), len(target_items)))
    )
    target_items.insert(index, task)

    affected = {item.id for item in locked}
    if task.id not in affected:
        affected.add(task.id)
    Task.objects.filter(id__in=affected).update(position=F("position") + TEMP_POSITION_OFFSET)
    Task.objects.filter(pk=task.pk).update(column=target, position=MOVING_TEMP_POSITION)

    if source_id != target_id:
        for index, item in enumerate(source_items):
            Task.objects.filter(pk=item.pk).update(position=index)
    for index, item in enumerate(target_items):
        Task.objects.filter(pk=item.pk).update(column=target, position=index)

    task.column = target
    task.position = target_items.index(task)


def create_task(
    *,
    actor,
    board_id,
    title: str,
    description: str = "",
    priority: int = 1,
    owner_id=None,
    draft_due_at: datetime | None = None,
    draft_acceptance_criteria: str = "",
    column_id=None,
) -> Task:
    title = title.strip()
    if not title:
        raise DomainError(
            "invalid_title", "Task title is required.", field_errors={"title": ["Required."]}
        )
    if priority not in {1, 2, 3}:
        raise DomainError("invalid_priority", "Priority must be 1, 2, or 3.")
    if priority == 3 and draft_due_at is None:
        raise DomainError("priority_requires_due", "Three-star draft tasks require a deadline.")
    if draft_due_at is not None:
        _validate_due(draft_due_at)

    with transaction.atomic():
        board = Board.objects.select_for_update().get(pk=board_id, archived=False)
        require_board_member(actor, board.id, for_update=True)
        owner = _eligible_owner(board, owner_id) if owner_id else None
        target_column = (
            _column_by_id(board, column_id)
            if column_id
            else _column(board, BoardColumn.State.BACKLOG)
        )
        task = Task.objects.create(
            board=board,
            column=target_column,
            title=title,
            description=description,
            priority=priority,
            current_owner=owner,
            position=_next_position(target_column),
            draft_due_at=draft_due_at,
            draft_acceptance_criteria=draft_acceptance_criteria,
            created_by=actor,
        )
        board.revision += 1
        board.save(update_fields=["revision", "updated_at"])
        _audit(board, task, actor, "create_task", after=_serialize_task(task))
        return task


def edit_task(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
    title: str | None = None,
    description: str | None = None,
    priority: int | None = None,
    owner_id=None,
    draft_due_at: datetime | None = None,
    draft_acceptance_criteria: str | None = None,
    recurrence_update: bool = False,
    recurrence_frequency: str | None = None,
    recurrence_next_at: datetime | None = None,
) -> Task:
    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_member(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        before = _serialize_task(task)

        if task.committed_at is not None and any(
            value is not None
            for value in (priority, owner_id, draft_due_at, draft_acceptance_criteria)
        ):
            raise DomainError(
                "protected_commitment",
                "Owner, stars, deadline and acceptance criteria require "
                "revise_commitment after commitment.",
                status=409,
            )
        if title is not None:
            cleaned = title.strip()
            if not cleaned:
                raise DomainError("invalid_title", "Task title is required.")
            task.title = cleaned
        if description is not None:
            task.description = description
        if task.committed_at is None:
            if priority is not None:
                if priority not in {1, 2, 3}:
                    raise DomainError("invalid_priority", "Priority must be 1, 2, or 3.")
                task.priority = priority
            if owner_id is not None:
                task.current_owner = _eligible_owner(board, owner_id)
            if draft_due_at is not None:
                _validate_due(draft_due_at)
                task.draft_due_at = draft_due_at
            if draft_acceptance_criteria is not None:
                task.draft_acceptance_criteria = draft_acceptance_criteria
            if task.priority == 3 and task.draft_due_at is None:
                raise DomainError(
                    "priority_requires_due", "Three-star draft tasks require a deadline."
                )

        if recurrence_update:
            configure_recurrence(
                task,
                frequency=recurrence_frequency or Task.Recurrence.NONE,
                next_at=recurrence_next_at,
            )

        _bump(board, task)
        task.save()
        _audit(board, task, actor, "edit_task", before=before, after=_serialize_task(task))
        return task


def commit_task(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
    owner_id=None,
    due_at: datetime | None = None,
    acceptance_criteria: str | None = None,
    reason: str = "Initial commitment",
) -> Task:
    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_manager(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        if task.committed_at is not None or task.column.state != BoardColumn.State.BACKLOG:
            raise DomainError(
                "already_committed", "Only backlog drafts can be committed.", status=409
            )

        chosen_owner_id = owner_id or task.current_owner_id
        if chosen_owner_id is None:
            raise DomainError("owner_required", "A committed task requires an accountable owner.")
        owner = _eligible_owner(board, chosen_owner_id)
        chosen_due = due_at or task.draft_due_at
        if chosen_due is None:
            raise DomainError("due_required", "A committed task requires a deadline.")
        _validate_due(chosen_due)
        criteria = (
            acceptance_criteria
            if acceptance_criteria is not None
            else task.draft_acceptance_criteria
        ).strip()
        if not criteria:
            raise DomainError("criteria_required", "Measurable acceptance criteria are required.")

        before = _serialize_task(task)
        previous_revision = (
            CommitmentRevision.objects.filter(task=task).aggregate(value=Max("revision"))["value"]
            or 0
        )
        commitment = CommitmentRevision.objects.create(
            task=task,
            revision=previous_revision + 1,
            owner=owner,
            due_at=chosen_due,
            priority=task.priority,
            acceptance_criteria=criteria,
            required_checklist_snapshot=_required_checklist_snapshot(task),
            actor=actor,
            reason=reason,
        )
        todo = _column(board, BoardColumn.State.TODO)
        _resequence_for_move(task, todo, None)
        task.current_owner = owner
        task.original_owner = owner
        task.current_commitment = commitment
        task.committed_at = now()
        task.row_version += 1
        board.revision += 1
        task.save()
        board.save(update_fields=["revision", "updated_at"])
        _audit(
            board,
            task,
            actor,
            "commit_task",
            reason=reason,
            before=before,
            after=_serialize_task(task),
        )
        from notifications.obligations import schedule_commitment_notifications

        schedule_commitment_notifications(task)
        return task


def move_task(
    *,
    actor,
    task_id,
    target_state: str = "",
    target_column_id=None,
    target_position: int | None,
    expected_version: int,
    expected_board_revision: int,
    reason: str = "",
) -> Task:
    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_member(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        if task.is_cancelled:
            raise DomainError("cancelled_task", "Cancelled tasks cannot be dragged.", status=409)

        if target_column_id:
            target = _column_by_id(board, target_column_id)
        else:
            if not target_state or target_state == BoardColumn.State.REVIEW:
                raise DomainError(
                    "invalid_transition",
                    "Cards can only be moved to an active list on this board.",
                    status=409,
                )
            target = _column(board, target_state)

        before = _serialize_task(task)
        _resequence_for_move(task, target, target_position)
        task.row_version += 1
        board.revision += 1
        task.save(update_fields=["column", "position", "row_version", "updated_at"])
        board.save(update_fields=["revision", "updated_at"])
        _audit(
            board,
            task,
            actor,
            "move_task",
            reason=reason,
            before=before,
            after=_serialize_task(task),
        )
        return task


def set_checklist_item(
    *,
    actor,
    task_id,
    item_id,
    checked: bool,
    expected_version: int,
    expected_board_revision: int,
) -> Task:
    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_member(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        if task.is_cancelled:
            raise DomainError("checklist_locked", "Cancelled cards cannot be updated.", status=409)
        item = ChecklistItem.objects.select_for_update().filter(pk=item_id, task=task).first()
        if item is None:
            raise DomainError("not_found", "Checklist item not found.", status=404)
        before = {"item_id": str(item.id), "checked": item.checked}
        item.checked = bool(checked)
        item.save(update_fields=["checked", "updated_at"])
        _bump(board, task)
        _audit(
            board,
            task,
            actor,
            "set_checklist_item",
            before=before,
            after={"item_id": str(item.id), "checked": item.checked},
        )
        return task


def propose_change(
    *, actor, task_id, proposed_changes: dict[str, Any], reason: str
) -> ChangeProposal:
    if not reason.strip():
        raise DomainError("reason_required", "A reason is required.")
    allowed = {"owner_id", "priority", "due_at", "acceptance_criteria", "required_checklist"}
    if not proposed_changes:
        raise DomainError("invalid_change", "At least one proposed change is required.")
    unknown = set(proposed_changes) - allowed
    if unknown:
        raise DomainError("invalid_change", f"Unsupported proposed fields: {sorted(unknown)}")
    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_member(actor, board.id, for_update=True)
        if task.committed_at is None:
            raise DomainError(
                "not_committed", "Use edit_task while the task is still a draft.", status=409
            )
        proposal = ChangeProposal.objects.create(
            task=task,
            proposer=actor,
            proposed_changes=proposed_changes,
            reason=reason,
        )
        board.revision += 1
        task.row_version += 1
        board.save(update_fields=["revision", "updated_at"])
        task.save(update_fields=["row_version", "updated_at"])
        _audit(
            board,
            task,
            actor,
            "propose_change",
            reason=reason,
            after={"proposal_id": str(proposal.id)},
        )
        return proposal


def _replace_required_checklist(task: Task, values: list[dict[str, Any]]) -> None:
    if not isinstance(values, list):
        raise DomainError("invalid_checklist", "Required checklist must be a list.")
    Task.objects.select_for_update().get(pk=task.pk)
    existing_non_required = list(
        task.checklist_items.select_for_update().filter(required=False).order_by("position")
    )
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            raise DomainError(
                "invalid_checklist",
                "Required checklist items must be objects.",
            )
        text = str(value.get("text", "")).strip()
        if not text:
            raise DomainError("invalid_checklist", "Required checklist items need text.")
        normalized.append(text[:500])

    task.checklist_items.filter(required=True).delete()
    for position, item in enumerate(existing_non_required):
        if item.position != position:
            item.position = position
            item.save(update_fields=["position"])
    base = len(existing_non_required)
    for index, text in enumerate(normalized):
        ChecklistItem.objects.create(
            task=task,
            text=text[:500],
            required=True,
            position=base + index,
            checked=False,
        )


def revise_commitment(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
    reason: str,
    owner_id=None,
    due_at: datetime | None = None,
    priority: int | None = None,
    acceptance_criteria: str | None = None,
    required_checklist: list[dict[str, Any]] | None = None,
) -> Task:
    if not reason.strip():
        raise DomainError("reason_required", "A manager revision requires a reason.")
    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_manager(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        if task.committed_at is None or task.current_commitment is None:
            raise DomainError(
                "not_committed", "Draft tasks do not have commitments to revise.", status=409
            )
        current = task.current_commitment
        owner = _eligible_owner(board, owner_id) if owner_id is not None else current.owner
        chosen_due = due_at if due_at is not None else current.due_at
        _validate_due(chosen_due)
        chosen_priority = priority if priority is not None else current.priority
        if chosen_priority not in {1, 2, 3}:
            raise DomainError("invalid_priority", "Priority must be 1, 2, or 3.")
        criteria = (
            acceptance_criteria.strip()
            if acceptance_criteria is not None
            else current.acceptance_criteria
        )
        if not criteria:
            raise DomainError("criteria_required", "Acceptance criteria cannot be empty.")

        pending = (
            Submission.objects.select_for_update(of=("self",))
            .filter(task=task, is_current=True, review__isnull=True)
            .first()
        )
        if pending is not None and (
            owner_id is not None
            or acceptance_criteria is not None
            or required_checklist is not None
        ):
            pending.is_current = False
            pending.save(update_fields=["is_current"])
            in_progress = _column(board, BoardColumn.State.IN_PROGRESS)
            _resequence_for_move(task, in_progress, None)

        if required_checklist is not None:
            _replace_required_checklist(task, required_checklist)

        before = _serialize_task(task)
        revision = CommitmentRevision.objects.create(
            task=task,
            revision=current.revision + 1,
            owner=owner,
            due_at=chosen_due,
            priority=chosen_priority,
            acceptance_criteria=criteria,
            required_checklist_snapshot=_required_checklist_snapshot(task),
            actor=actor,
            reason=reason,
        )
        task.current_commitment = revision
        task.current_owner = owner
        task.priority = chosen_priority
        task.row_version += 1
        board.revision += 1
        task.save()
        board.save(update_fields=["revision", "updated_at"])
        _audit(
            board,
            task,
            actor,
            "revise_commitment",
            reason=reason,
            before=before,
            after=_serialize_task(task),
        )
        from notifications.obligations import schedule_commitment_notifications

        schedule_commitment_notifications(task)
        return task


def submit_result(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
    result_summary: str,
    evidence_links: list[str],
    target_value=None,
    actual_value=None,
    unit: str = "",
) -> Task:
    summary = result_summary.strip()
    if not summary:
        raise DomainError("result_required", "Result summary is required.")
    links = _validate_evidence_links(evidence_links)

    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        membership = require_board_member(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        if task.current_commitment is None or task.current_owner_id is None:
            raise DomainError("not_committed", "Only committed tasks can be submitted.", status=409)
        if task.is_cancelled:
            raise DomainError(
                "invalid_transition", "Cancelled tasks cannot be submitted.", status=409
            )
        if actor.id != task.current_owner_id and membership.role != BoardMembership.Role.MANAGER:
            raise DomainError(
                "submit_forbidden",
                "Only the accountable owner or a board manager may submit.",
                status=403,
            )

        incomplete = list(
            task.checklist_items.filter(required=True, checked=False).values_list("id", flat=True)
        )
        if incomplete:
            raise DomainError(
                "required_checklist_incomplete",
                "Complete every required checklist item before submission.",
                field_errors={"checklist": [str(value) for value in incomplete]},
            )
        if Submission.objects.filter(task=task, is_current=True).exists():
            raise DomainError(
                "submission_exists", "A current submission already exists.", status=409
            )

        before = _serialize_task(task)
        commitment = task.current_commitment
        owner = task.current_owner
        if owner is None:
            raise DomainError("invalid_owner", "Committed task owner is unavailable.", status=409)
        submission = Submission.objects.create(
            task=task,
            commitment=commitment,
            accountable_owner=owner,
            submitting_actor=actor,
            result_summary=summary,
            evidence_links=links,
            criteria_snapshot=commitment.acceptance_criteria,
            checklist_snapshot=[
                {
                    "id": str(item.id),
                    "text": item.text,
                    "required": item.required,
                    "checked": item.checked,
                }
                for item in task.checklist_items.order_by("position")
            ],
            target_value=target_value,
            actual_value=actual_value,
            unit=unit[:64],
        )
        task.row_version += 1
        board.revision += 1
        task.save(update_fields=["row_version", "updated_at"])
        board.save(update_fields=["revision", "updated_at"])
        _audit(board, task, actor, "submit_result", before=before, after=_serialize_task(task))
        from notifications.obligations import schedule_review_requests

        schedule_review_requests(task, submission)
        return task


def review_submission(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
    decision: str,
    feedback: str = "",
) -> Task:
    if decision not in {Review.Decision.ACCEPTED, Review.Decision.REJECTED}:
        raise DomainError("invalid_decision", "Decision must be ACCEPTED or REJECTED.")

    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_manager(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        submission = (
            Submission.objects.select_for_update()
            .select_related("accountable_owner", "submitting_actor")
            .filter(task=task, is_current=True)
            .first()
        )
        if submission is None or hasattr(submission, "review"):
            raise DomainError(
                "stale_submission", "No current unreviewed submission exists.", status=409
            )
        if actor.id in {submission.accountable_owner_id, submission.submitting_actor_id}:
            raise DomainError(
                "self_review_forbidden",
                "The reviewer must be independent of the owner and submitting actor.",
                status=403,
            )

        before = _serialize_task(task)
        Review.objects.create(
            submission=submission,
            reviewer=actor,
            decision=decision,
            feedback=feedback,
        )
        if decision == Review.Decision.ACCEPTED:
            target = _column(board, BoardColumn.State.DONE)
        else:
            submission.is_current = False
            submission.save(update_fields=["is_current"])
            target = _column(board, BoardColumn.State.IN_PROGRESS)
        _resequence_for_move(task, target, None)
        task.row_version += 1
        board.revision += 1
        task.save(update_fields=["column", "position", "row_version", "updated_at"])
        board.save(update_fields=["revision", "updated_at"])
        _audit(
            board,
            task,
            actor,
            "review_submission",
            reason=feedback,
            before=before,
            after={**_serialize_task(task), "decision": decision},
        )
        return task


def reopen_task(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
    reason: str,
) -> Task:
    if not reason.strip():
        raise DomainError("reason_required", "Reopening requires a reason.")
    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_manager(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        if task.column.state != BoardColumn.State.DONE or task.is_cancelled:
            raise DomainError(
                "invalid_transition", "Only an accepted done task can be reopened.", status=409
            )
        current = Submission.objects.select_for_update().filter(task=task, is_current=True).first()
        if current is not None:
            current.is_current = False
            current.save(update_fields=["is_current"])
        before = _serialize_task(task)
        target = _column(board, BoardColumn.State.IN_PROGRESS)
        _resequence_for_move(task, target, None)
        task.row_version += 1
        board.revision += 1
        task.save(update_fields=["column", "position", "row_version", "updated_at"])
        board.save(update_fields=["revision", "updated_at"])
        _audit(
            board,
            task,
            actor,
            "reopen_task",
            reason=reason,
            before=before,
            after=_serialize_task(task),
        )
        return task


def cancel_task(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
    reason: str,
) -> Task:
    if not reason.strip():
        raise DomainError("reason_required", "Cancellation requires a reason.")
    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_manager(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        if task.is_cancelled:
            raise DomainError("already_cancelled", "Task is already cancelled.", status=409)
        before = _serialize_task(task)
        task.is_cancelled = True
        task.cancelled_at = now()
        task.cancelled_reason = reason
        task.row_version += 1
        board.revision += 1
        task.save(
            update_fields=[
                "is_cancelled",
                "cancelled_at",
                "cancelled_reason",
                "row_version",
                "updated_at",
            ]
        )
        board.save(update_fields=["revision", "updated_at"])
        _audit(
            board,
            task,
            actor,
            "cancel_task",
            reason=reason,
            before=before,
            after=_serialize_task(task),
        )
        return task


def restore_cancelled_task(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
    reason: str,
) -> Task:
    if not reason.strip():
        raise DomainError("reason_required", "Restoring a cancellation requires a reason.")
    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_manager(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        if not task.is_cancelled:
            raise DomainError("not_cancelled", "Task is not cancelled.", status=409)
        before = _serialize_task(task)
        task.is_cancelled = False
        task.cancelled_at = None
        task.cancelled_reason = ""
        task.position = _next_position(task.column)
        task.row_version += 1
        board.revision += 1
        task.save()
        board.save(update_fields=["revision", "updated_at"])
        _audit(
            board,
            task,
            actor,
            "restore_cancelled_task",
            reason=reason,
            before=before,
            after=_serialize_task(task),
        )
        return task


def replace_draft_checklist(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
    items: list[dict[str, Any]],
) -> Task:
    if not isinstance(items, list) or len(items) > 100:
        raise DomainError(
            "invalid_checklist",
            "Checklist must be a list with at most 100 items.",
        )
    normalized: list[dict[str, Any]] = []
    for value in items:
        if not isinstance(value, dict):
            raise DomainError("invalid_checklist", "Each checklist item must be an object.")
        text = str(value.get("text", "")).strip()
        if not text:
            raise DomainError("invalid_checklist", "Checklist items require text.")
        normalized.append(
            {
                "text": text[:500],
                "required": bool(value.get("required", False)),
            }
        )

    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_member(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        if task.committed_at is not None:
            raise DomainError(
                "protected_commitment",
                "Checklist structure is frozen after commitment. Use revise_commitment.",
                status=409,
            )
        before = [
            {
                "id": str(item.id),
                "text": item.text,
                "required": item.required,
                "position": item.position,
            }
            for item in task.checklist_items.order_by("position")
        ]
        task.checklist_items.all().delete()
        for index, value in enumerate(normalized):
            ChecklistItem.objects.create(
                task=task,
                text=value["text"],
                required=value["required"],
                position=index,
                checked=False,
            )
        _bump(board, task)
        _audit(
            board,
            task,
            actor,
            "replace_draft_checklist",
            before={"items": before},
            after={
                "items": [
                    {
                        "id": str(item.id),
                        "text": item.text,
                        "required": item.required,
                        "position": item.position,
                    }
                    for item in task.checklist_items.order_by("position")
                ]
            },
        )
        return task


def add_comment(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
    body: str,
) -> Task:
    cleaned = body.strip()
    if not cleaned:
        raise DomainError("comment_required", "Comment text is required.")
    if len(cleaned) > 10000:
        raise DomainError("comment_too_long", "Comment cannot exceed 10000 characters.")

    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_member(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        comment = Comment.objects.create(task=task, author=actor, body=cleaned)
        _bump(board, task)
        _audit(
            board,
            task,
            actor,
            "add_comment",
            after={"comment_id": str(comment.id)},
        )
        return task


def correct_comment(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
    comment_id,
    body: str,
) -> Task:
    cleaned = body.strip()
    if not cleaned:
        raise DomainError("comment_required", "Comment text is required.")
    if len(cleaned) > 10000:
        raise DomainError("comment_too_long", "Comment cannot exceed 10000 characters.")

    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        membership = require_board_member(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        comment = Comment.objects.select_for_update().filter(pk=comment_id, task=task).first()
        if comment is None:
            raise DomainError("not_found", "Comment not found.", status=404)
        if comment.author_id != actor.id and membership.role != BoardMembership.Role.MANAGER:
            raise DomainError(
                "comment_correction_forbidden",
                "Only the comment author or a board manager can correct it.",
                status=403,
            )
        if comment.body == cleaned:
            return task
        previous = comment.body
        CommentEditHistory.objects.create(
            comment=comment,
            editor=actor,
            previous_body=previous,
            replacement_body=cleaned,
        )
        comment.body = cleaned
        comment.corrected_at = now()
        comment.save(update_fields=["body", "corrected_at"])
        _bump(board, task)
        _audit(
            board,
            task,
            actor,
            "correct_comment",
            before={"comment_id": str(comment.id)},
            after={"comment_id": str(comment.id), "corrected": True},
        )
        return task


def resolve_change_proposal(
    *,
    actor,
    task_id,
    expected_version: int,
    expected_board_revision: int,
    proposal_id,
    decision: str,
    reason: str,
) -> Task:
    if decision not in {
        ChangeProposal.Status.ACCEPTED,
        ChangeProposal.Status.DECLINED,
    }:
        raise DomainError(
            "invalid_decision",
            "Proposal decision must be ACCEPTED or DECLINED.",
        )
    if not reason.strip():
        raise DomainError("reason_required", "A proposal resolution requires a reason.")

    if decision == ChangeProposal.Status.ACCEPTED:
        proposal = ChangeProposal.objects.filter(
            pk=proposal_id,
            task_id=task_id,
            status=ChangeProposal.Status.PENDING,
        ).first()
        if proposal is None:
            raise DomainError(
                "proposal_not_found",
                "Pending proposal not found.",
                status=404,
            )
        changes = dict(proposal.proposed_changes)
        due_at = None
        if "due_at" in changes:
            raw_due = changes.get("due_at")
            if not isinstance(raw_due, str):
                raise DomainError(
                    "invalid_datetime",
                    "Proposed due_at must be an ISO datetime.",
                )
            due_at = parse_datetime(raw_due)
            if due_at is None:
                raise DomainError("invalid_datetime", "Proposed due_at is invalid.")
        priority = None
        if "priority" in changes:
            try:
                priority = int(changes["priority"])
            except (TypeError, ValueError) as exc:
                raise DomainError(
                    "invalid_priority",
                    "Proposed priority must be 1, 2, or 3.",
                ) from exc
        required_checklist = changes.get("required_checklist")
        if required_checklist is not None and not isinstance(required_checklist, list):
            raise DomainError(
                "invalid_checklist",
                "Proposed required_checklist must be a list.",
            )

        with transaction.atomic():
            task = revise_commitment(
                actor=actor,
                task_id=task_id,
                expected_version=expected_version,
                expected_board_revision=expected_board_revision,
                reason=reason,
                owner_id=changes.get("owner_id"),
                due_at=due_at,
                priority=priority,
                acceptance_criteria=changes.get("acceptance_criteria"),
                required_checklist=required_checklist,
            )
            locked = (
                ChangeProposal.objects.select_for_update()
                .filter(
                    pk=proposal_id,
                    task_id=task_id,
                    status=ChangeProposal.Status.PENDING,
                )
                .first()
            )
            if locked is None:
                raise DomainError(
                    "proposal_changed",
                    "Proposal changed while it was being accepted.",
                    status=409,
                )
            locked.status = ChangeProposal.Status.ACCEPTED
            locked.resolved_by = actor
            locked.resolution_reason = reason[:2000]
            locked.resolved_at = now()
            locked.save(
                update_fields=[
                    "status",
                    "resolved_by",
                    "resolution_reason",
                    "resolved_at",
                ]
            )
            return task

    with transaction.atomic():
        board, task = _board_and_task_for_update(task_id)
        require_board_manager(actor, board.id, for_update=True)
        _require_expected(task, board, expected_version, expected_board_revision)
        proposal = (
            ChangeProposal.objects.select_for_update()
            .filter(
                pk=proposal_id,
                task=task,
                status=ChangeProposal.Status.PENDING,
            )
            .first()
        )
        if proposal is None:
            raise DomainError(
                "proposal_not_found",
                "Pending proposal not found.",
                status=404,
            )
        proposal.status = ChangeProposal.Status.DECLINED
        proposal.resolved_by = actor
        proposal.resolution_reason = reason[:2000]
        proposal.resolved_at = now()
        proposal.save(
            update_fields=[
                "status",
                "resolved_by",
                "resolution_reason",
                "resolved_at",
            ]
        )
        _bump(board, task)
        _audit(
            board,
            task,
            actor,
            "decline_change_proposal",
            reason=reason,
            after={"proposal_id": str(proposal.id)},
        )
        return task
