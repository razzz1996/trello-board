from __future__ import annotations

from core.idempotency import IdempotencyError, run_idempotent
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from rest_framework.response import Response
from rest_framework.views import APIView
from workitems.serializers import TaskSerializer

from .models import Board, BoardColumn, BoardMembership
from .permissions import require_board_member, require_site_admin, visible_boards

User = get_user_model()
STANDARD_COLUMNS = [
    (BoardColumn.State.BACKLOG, "Backlog"),
    (BoardColumn.State.TODO, "To Do"),
    (BoardColumn.State.IN_PROGRESS, "In Progress"),
    (BoardColumn.State.BLOCKED, "Blocked"),
    (BoardColumn.State.REVIEW, "Review"),
    (BoardColumn.State.DONE, "Done"),
]


def _board_summary(board: Board) -> dict:
    return {
        "id": str(board.id),
        "name": board.name,
        "revision": board.revision,
        "archived": board.archived,
    }


def _idempotency_error(exc: IdempotencyError) -> Response:
    return Response(
        {"code": exc.code, "message": exc.message, "field_errors": {}, "request_id": None},
        status=exc.status,
    )


class BoardListCreateView(APIView):
    def get(self, request):
        if request.user.is_staff or request.user.is_superuser:
            boards = Board.objects.all().order_by("name")
        else:
            boards = visible_boards(request.user).order_by("name")
        return Response([_board_summary(board) for board in boards])

    def post(self, request):
        require_site_admin(request.user)
        payload = request.data if isinstance(request.data, dict) else {}
        name = str(payload.get("name", "")).strip()
        manager_ids = payload.get("manager_user_ids", [])
        if not name or len(name) > 200:
            return Response(
                {
                    "code": "invalid_name",
                    "message": "Board name is required.",
                    "field_errors": {},
                    "request_id": None,
                },
                status=400,
            )
        if not isinstance(manager_ids, list) or not manager_ids:
            return Response(
                {
                    "code": "manager_required",
                    "message": "At least one initial board manager is required.",
                    "field_errors": {},
                    "request_id": None,
                },
                status=400,
            )

        try:
            unique_manager_ids = set(manager_ids)
            users = list(
                User.objects.filter(
                    id__in=unique_manager_ids,
                    is_active=True,
                )
            )
        except (TypeError, ValueError):
            return Response(
                {
                    "code": "invalid_manager",
                    "message": "Every manager ID must be valid.",
                    "field_errors": {},
                    "request_id": None,
                },
                status=400,
            )
        if len(users) != len(unique_manager_ids):
            return Response(
                {
                    "code": "invalid_manager",
                    "message": "Every manager must be an active user.",
                    "field_errors": {},
                    "request_id": None,
                },
                status=400,
            )

        def create():
            board = Board.objects.create(name=name, created_by=request.user)
            for index, (state, label) in enumerate(STANDARD_COLUMNS):
                BoardColumn.objects.create(board=board, state=state, name=label, position=index)
            for user in users:
                BoardMembership.objects.create(
                    board=board,
                    user=user,
                    role=BoardMembership.Role.MANAGER,
                    created_by=request.user,
                )
            return 201, _board_summary(board)

        try:
            result = run_idempotent(
                actor=request.user,
                endpoint="/api/v1/boards",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=create,
                authorize_replay=lambda: require_site_admin(request.user),
            )
        except IdempotencyError as exc:
            return _idempotency_error(exc)
        return Response(result.body, status=result.status)


class BoardSnapshotView(APIView):
    def get(self, request, board_id):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            membership = require_board_member(request.user, board_id)
            board = Board.objects.get(pk=membership.board_id)
            columns = list(board.columns.order_by("position"))
            tasks = (
                board.tasks.filter(is_cancelled=False)
                .select_related("column", "current_owner", "original_owner", "current_commitment")
                .prefetch_related("checklist_items", "submissions__review")
                .order_by("column__position", "position", "id")
            )
            grouped: dict[str, list[dict]] = {str(column.id): [] for column in columns}
            for task in tasks:
                grouped[str(task.column_id)].append(TaskSerializer(task).data)
            roster = list(
                board.memberships.filter(is_active=True, user__is_active=True)
                .select_related("user")
                .order_by("user__username")
            )
            return Response(
                {
                    "board": _board_summary(board),
                    "membership": {"role": membership.role},
                    "members": [
                        {
                            "id": str(item.user_id),
                            "username": item.user.get_username(),
                            "role": item.role,
                        }
                        for item in roster
                    ],
                    "revision": board.revision,
                    "columns": [
                        {
                            "id": str(column.id),
                            "state": column.state,
                            "name": column.name,
                            "position": column.position,
                            "tasks": grouped[str(column.id)],
                        }
                        for column in columns
                    ],
                }
            )
