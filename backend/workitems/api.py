from __future__ import annotations

from datetime import datetime
from typing import Any

from boards.models import BoardMembership
from boards.permissions import require_board_manager, require_board_member
from core.idempotency import IdempotencyError, run_idempotent
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils.dateparse import parse_datetime
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .deletion import delete_task
from .errors import DomainError
from .models import Task
from .serializers import TaskSerializer


def _error(code: str, message: str, status: int, field_errors=None) -> Response:
    return Response(
        {
            "code": code,
            "message": message,
            "field_errors": field_errors or {},
            "request_id": None,
        },
        status=status,
    )


def _datetime(value: Any, field: str) -> datetime | None:
    if value in {None, ""}:
        return None
    if not isinstance(value, str):
        raise DomainError("invalid_datetime", f"{field} must be an ISO datetime string.")
    parsed = parse_datetime(value)
    if parsed is None or parsed.tzinfo is None:
        raise DomainError(
            "invalid_datetime",
            f"{field} must include a timezone offset.",
            field_errors={field: ["Timezone offset required."]},
        )
    return parsed


def _serialized(task: Task) -> dict[str, Any]:
    task.refresh_from_db()
    return dict(TaskSerializer(task).data)


class TaskCollectionView(APIView):
    def get(self, request):
        qs = (
            Task.objects.filter(board__archived=False)
            .select_related(
                "board",
                "column",
                "current_owner",
                "original_owner",
                "current_commitment",
            )
            .prefetch_related(
                "checklist_items",
                "comments__author",
                "comments__history",
                "change_proposals",
                "submissions__review",
            )
            .distinct()
        )
        status_filter = request.query_params.get("status")
        if status_filter == "CANCELLED":
            qs = qs.filter(is_cancelled=True)
        else:
            qs = qs.filter(is_cancelled=False)
            if status_filter:
                qs = qs.filter(column__state=status_filter)

        if board_id := request.query_params.get("board"):
            qs = qs.filter(board_id=board_id)
        if owner_id := request.query_params.get("owner"):
            qs = qs.filter(current_owner_id=owner_id)
        if priority := request.query_params.get("priority"):
            try:
                priority_value = int(priority)
            except ValueError:
                return _error("invalid_priority", "Priority filter must be an integer.", 400)
            if priority_value not in {1, 2, 3}:
                return _error("invalid_priority", "Priority filter must be 1, 2, or 3.", 400)
            qs = qs.filter(priority=priority_value)

        try:
            limit = min(max(int(request.query_params.get("limit", "100")), 1), 100)
        except ValueError:
            return _error("invalid_limit", "Limit must be an integer.", 400)
        rows = qs.order_by("current_commitment__due_at", "priority", "created_at")[:limit]
        return Response(TaskSerializer(rows, many=True).data)

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        try:
            board_id = payload["board_id"]
            require_board_member(request.user, board_id)
            draft_due_at = _datetime(payload.get("draft_due_at"), "draft_due_at")

            def create():
                task = services.create_task(
                    actor=request.user,
                    board_id=board_id,
                    title=str(payload.get("title", "")),
                    description=str(payload.get("description", "")),
                    priority=int(payload.get("priority", 1)),
                    owner_id=payload.get("owner_id"),
                    draft_due_at=draft_due_at,
                    draft_acceptance_criteria=str(payload.get("draft_acceptance_criteria", "")),
                    column_id=payload.get("column_id"),
                )
                return 201, _serialized(task)

            def authorize_replay() -> None:
                require_board_member(request.user, board_id)

            result = run_idempotent(
                actor=request.user,
                endpoint="/api/v1/tasks",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=create,
                authorize_replay=authorize_replay,
            )
            return Response(result.body, status=result.status)
        except KeyError:
            return _error("board_required", "board_id is required.", 400)
        except ValueError:
            return _error("invalid_priority", "Priority must be an integer.", 400)
        except DomainError as exc:
            return _error(exc.code, exc.message, exc.status, exc.field_errors)
        except IdempotencyError as exc:
            return _error(exc.code, exc.message, exc.status)


class TaskDeleteView(APIView):
    def post(self, request, task_id):
        payload = request.data if isinstance(request.data, dict) else {}
        try:
            expected_version = int(payload["expected_version"])
            expected_board_revision = int(payload["expected_board_revision"])

            def execute():
                body = delete_task(
                    actor=request.user,
                    task_id=task_id,
                    expected_version=expected_version,
                    expected_board_revision=expected_board_revision,
                )
                return 200, body

            result = run_idempotent(
                actor=request.user,
                endpoint=f"/api/v1/tasks/{task_id}/delete",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=execute,
            )
            return Response(result.body, status=result.status)
        except KeyError:
            return _error(
                "version_required",
                "expected_version and expected_board_revision are required.",
                400,
            )
        except ValueError:
            return _error("invalid_version", "Expected versions must be integers.", 400)
        except DomainError as exc:
            return _error(exc.code, exc.message, exc.status, exc.field_errors)
        except IdempotencyError as exc:
            return _error(exc.code, exc.message, exc.status)


MANAGER_COMMANDS = {
    "commit_task",
    "revise_commitment",
    "review_submission",
    "reopen_task",
    "cancel_task",
    "restore_cancelled_task",
    "resolve_change_proposal",
}


class TaskCommandView(APIView):
    def _authorize_replay(self, request, task_id, command: str) -> None:
        task = Task.objects.only("board_id", "current_owner_id").filter(pk=task_id).first()
        if task is None:
            raise Http404
        if command in MANAGER_COMMANDS:
            require_board_manager(request.user, task.board_id)
            return
        membership = require_board_member(request.user, task.board_id)
        if command == "submit_result":
            if (
                request.user.id != task.current_owner_id
                and membership.role != BoardMembership.Role.MANAGER
            ):
                raise PermissionDenied

    def post(self, request, task_id, command: str):
        payload = request.data if isinstance(request.data, dict) else {}
        try:
            expected_version = int(payload["expected_version"])
            expected_board_revision = int(payload["expected_board_revision"])

            def execute():
                task = self._dispatch(
                    request,
                    task_id,
                    command,
                    payload,
                    expected_version,
                    expected_board_revision,
                )
                return 200, _serialized(task)

            result = run_idempotent(
                actor=request.user,
                endpoint=f"/api/v1/tasks/{task_id}/commands/{command}",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=execute,
                authorize_replay=lambda: self._authorize_replay(
                    request,
                    task_id,
                    command,
                ),
            )
            return Response(result.body, status=result.status)
        except KeyError:
            return _error(
                "version_required",
                "expected_version and expected_board_revision are required.",
                400,
            )
        except ValueError:
            return _error("invalid_version", "Expected versions must be integers.", 400)
        except DomainError as exc:
            return _error(exc.code, exc.message, exc.status, exc.field_errors)
        except IdempotencyError as exc:
            return _error(exc.code, exc.message, exc.status)

    def _dispatch(
        self,
        request,
        task_id,
        command: str,
        payload: dict[str, Any],
        expected_version: int,
        expected_board_revision: int,
    ) -> Task:
        common = {
            "actor": request.user,
            "task_id": task_id,
            "expected_version": expected_version,
            "expected_board_revision": expected_board_revision,
        }
        if command == "edit_task":
            recurrence_update = "recurrence_frequency" in payload or "recurrence_next_at" in payload
            return services.edit_task(
                **common,
                title=payload.get("title"),
                description=payload.get("description"),
                priority=payload.get("priority"),
                owner_id=payload.get("owner_id"),
                draft_due_at=_datetime(
                    payload.get("draft_due_at"),
                    "draft_due_at",
                ),
                draft_acceptance_criteria=payload.get("draft_acceptance_criteria"),
                recurrence_update=recurrence_update,
                recurrence_frequency=payload.get("recurrence_frequency"),
                recurrence_next_at=_datetime(
                    payload.get("recurrence_next_at"),
                    "recurrence_next_at",
                ),
            )
        if command == "move_task":
            return services.move_task(
                **common,
                target_state=str(payload.get("target_state", "")),
                target_column_id=payload.get("target_column_id"),
                target_position=payload.get("target_position"),
                reason=str(payload.get("reason", "")),
            )
        if command == "commit_task":
            return services.commit_task(
                **common,
                owner_id=payload.get("owner_id"),
                due_at=_datetime(payload.get("due_at"), "due_at"),
                acceptance_criteria=payload.get("acceptance_criteria"),
                reason=str(payload.get("reason", "Initial commitment")),
            )
        if command == "revise_commitment":
            priority = payload.get("priority")
            if priority is not None:
                priority = int(priority)
            return services.revise_commitment(
                **common,
                reason=str(payload.get("reason", "")),
                owner_id=payload.get("owner_id"),
                due_at=_datetime(payload.get("due_at"), "due_at"),
                priority=priority,
                acceptance_criteria=payload.get("acceptance_criteria"),
                required_checklist=payload.get("required_checklist"),
            )
        if command == "submit_result":
            links = payload.get("evidence_links", [])
            if not isinstance(links, list):
                raise DomainError(
                    "invalid_evidence",
                    "evidence_links must be a list.",
                )
            return services.submit_result(
                **common,
                result_summary=str(payload.get("result_summary", "")),
                evidence_links=links,
                target_value=payload.get("target_value"),
                actual_value=payload.get("actual_value"),
                unit=str(payload.get("unit", "")),
            )
        if command == "review_submission":
            return services.review_submission(
                **common,
                decision=str(payload.get("decision", "")),
                feedback=str(payload.get("feedback", "")),
            )
        if command == "reopen_task":
            return services.reopen_task(
                **common,
                reason=str(payload.get("reason", "")),
            )
        if command == "cancel_task":
            return services.cancel_task(
                **common,
                reason=str(payload.get("reason", "")),
            )
        if command == "restore_cancelled_task":
            return services.restore_cancelled_task(
                **common,
                reason=str(payload.get("reason", "")),
            )
        if command == "set_checklist_item":
            return services.set_checklist_item(
                **common,
                item_id=payload.get("item_id"),
                checked=bool(payload.get("checked")),
            )
        if command == "replace_draft_checklist":
            items = payload.get("items", [])
            if not isinstance(items, list):
                raise DomainError(
                    "invalid_checklist",
                    "items must be a list.",
                )
            return services.replace_draft_checklist(
                **common,
                items=items,
            )
        if command == "add_comment":
            return services.add_comment(
                **common,
                body=str(payload.get("body", "")),
            )
        if command == "correct_comment":
            return services.correct_comment(
                **common,
                comment_id=payload.get("comment_id"),
                body=str(payload.get("body", "")),
            )
        if command == "resolve_change_proposal":
            return services.resolve_change_proposal(
                **common,
                proposal_id=payload.get("proposal_id"),
                decision=str(payload.get("decision", "")),
                reason=str(payload.get("reason", "")),
            )
        if command == "propose_change":
            changes = payload.get("proposed_changes", {})
            if not isinstance(changes, dict):
                raise DomainError(
                    "invalid_change",
                    "proposed_changes must be an object.",
                )
            services.propose_change(
                actor=request.user,
                task_id=task_id,
                proposed_changes=changes,
                reason=str(payload.get("reason", "")),
            )
            task = Task.objects.get(pk=task_id)
            return task
        raise DomainError(
            "unknown_command",
            f"Unknown task command: {command}",
            status=404,
        )
