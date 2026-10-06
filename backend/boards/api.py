from __future__ import annotations

from uuid import UUID, uuid4

from core.idempotency import IdempotencyError, run_idempotent
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import Max
from rest_framework.response import Response
from rest_framework.views import APIView
from workitems.models import AuditEvent
from workitems.serializers import TaskSerializer

from .deletion import BoardDeletionError, delete_board
from .models import Board, BoardColumn, BoardMembership
from .permissions import (
    require_board_manager_or_site_admin,
    require_board_member,
    require_site_admin,
    visible_boards,
)

User = get_user_model()
STANDARD_COLUMNS = [
    (BoardColumn.State.BACKLOG, "Inbox"),
    (BoardColumn.State.TODO, "To Do"),
    (BoardColumn.State.IN_PROGRESS, "In Progress"),
    (BoardColumn.State.BLOCKED, "Later"),
    (BoardColumn.State.DONE, "Done"),
]


def _board_summary(board: Board) -> dict:
    return {
        "id": str(board.id),
        "name": board.name,
        "revision": board.revision,
        "archived": board.archived,
    }


def _column_payload(column: BoardColumn) -> dict[str, object]:
    return {
        "id": str(column.id),
        "state": column.state,
        "name": column.name,
        "position": column.position,
        "is_custom": column.is_custom,
    }


def _idempotency_error(exc: IdempotencyError) -> Response:
    return Response(
        {"code": exc.code, "message": exc.message, "field_errors": {}, "request_id": None},
        status=exc.status,
    )


class BoardAdminError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _board_admin_error(exc: BoardAdminError) -> Response:
    return Response(
        {"code": exc.code, "message": exc.message, "field_errors": {}, "request_id": None},
        status=exc.status,
    )


def _authorize_board_manager_or_admin(user, board_id) -> None:
    require_board_manager_or_site_admin(user, board_id)


def _authorize_board_member(user, board_id) -> None:
    require_board_member(user, board_id)


def _membership_payload(item: BoardMembership) -> dict[str, object]:
    return {
        "user_id": str(item.user_id),
        "username": item.user.get_username(),
        "role": item.role,
        "is_active": item.is_active,
    }


def _active_manager_count_for_update(board: Board) -> int:
    ids = list(
        BoardMembership.objects.select_for_update()
        .filter(
            board=board,
            role=BoardMembership.Role.MANAGER,
            is_active=True,
            user__is_active=True,
        )
        .values_list("id", flat=True)
    )
    return len(ids)


def _audit_board_membership(
    *,
    board: Board,
    actor,
    action: str,
    reason: str,
    before: dict[str, object],
    after: dict[str, object],
) -> None:
    board.revision += 1
    board.save(update_fields=["revision", "updated_at"])
    AuditEvent.objects.create(
        board=board,
        board_revision=board.revision,
        task=None,
        actor=actor,
        action=action,
        reason=reason[:2000],
        before=before,
        after=after,
    )


class BoardListCreateView(APIView):
    def get(self, request):
        include_all = str(request.query_params.get("all", "")).lower() in {"1", "true", "yes"}
        if include_all:
            require_site_admin(request.user)
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
        if not isinstance(manager_ids, list):
            return Response(
                {
                    "code": "invalid_manager",
                    "message": "manager_user_ids must be a list when provided.",
                    "field_errors": {"manager_user_ids": ["Expected a list."]},
                    "request_id": None,
                },
                status=400,
            )

        try:
            requested_manager_ids = {str(value) for value in manager_ids if str(value).strip()}
            requested_manager_ids.add(str(request.user.id))
            requested_managers = list(
                User.objects.filter(
                    id__in=requested_manager_ids,
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
        if len(requested_managers) != len(requested_manager_ids):
            return Response(
                {
                    "code": "invalid_manager",
                    "message": "Every manager must be an active user.",
                    "field_errors": {},
                    "request_id": None,
                },
                status=400,
            )
        users = list(User.objects.filter(is_active=True).order_by("username"))

        def create():
            board = Board.objects.create(name=name, created_by=request.user)
            for index, (state, label) in enumerate(STANDARD_COLUMNS):
                BoardColumn.objects.create(board=board, state=state, name=label, position=index)
            manager_user_ids: list[str] = []
            for user in users:
                is_manager = (
                    user.is_staff or user.is_superuser or str(user.id) in requested_manager_ids
                )
                role = BoardMembership.Role.MANAGER if is_manager else BoardMembership.Role.MEMBER
                BoardMembership.objects.create(
                    board=board,
                    user=user,
                    role=role,
                    created_by=request.user,
                )
                if is_manager:
                    manager_user_ids.append(str(user.id))
            AuditEvent.objects.create(
                board=board,
                board_revision=board.revision,
                task=None,
                actor=request.user,
                action="create_board",
                reason=str(payload.get("reason", ""))[:2000],
                before={},
                after={
                    "board_id": str(board.id),
                    "name": board.name,
                    "manager_user_ids": manager_user_ids,
                    "member_count": len(users),
                },
            )
            return 201, _board_summary(board)

        try:
            result = run_idempotent(
                actor=request.user,
                endpoint="/api/v1/boards",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=create,
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
            etag = f'"board-{board.id}-{board.revision}"'
            if request.headers.get("If-None-Match") == etag:
                response = Response(status=304)
                response.headers["ETag"] = etag
                return response
            columns = list(
                board.columns.exclude(state=BoardColumn.State.REVIEW).order_by("position")
            )
            tasks = (
                board.tasks.filter(is_cancelled=False)
                .exclude(column__state=BoardColumn.State.REVIEW)
                .select_related("column", "current_owner", "original_owner", "current_commitment")
                .prefetch_related(
                    "checklist_items",
                    "comments__author",
                    "comments__history",
                    "change_proposals",
                    "submissions__review",
                )
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
            response = Response(
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
                            "is_custom": column.is_custom,
                            "tasks": grouped[str(column.id)],
                        }
                        for column in columns
                    ],
                }
            )
            response.headers["ETag"] = etag
            return response


MAX_BOARD_COLUMNS = 20


class BoardColumnCollectionView(APIView):
    def post(self, request, board_id):
        require_board_member(request.user, board_id)
        payload = request.data if isinstance(request.data, dict) else {}
        name = str(payload.get("name", "")).strip()
        if not name or len(name) > 100:
            return _board_admin_error(
                BoardAdminError("invalid_name", "List name is required and must be 100 characters or less.")
            )

        def create():
            with transaction.atomic():
                board = Board.objects.select_for_update().filter(pk=board_id, archived=False).first()
                if board is None:
                    raise BoardAdminError("not_found", "Board not found.", 404)
                require_board_member(request.user, board.id, for_update=True)
                if board.columns.exclude(state=BoardColumn.State.REVIEW).count() >= MAX_BOARD_COLUMNS:
                    raise BoardAdminError(
                        "list_limit",
                        f"A board can contain up to {MAX_BOARD_COLUMNS} active lists.",
                        409,
                    )
                current_max = board.columns.aggregate(value=Max("position"))["value"]
                position = 0 if current_max is None else int(current_max) + 1
                column = BoardColumn.objects.create(
                    board=board,
                    state=f"CUSTOM_{uuid4().hex[:20].upper()}",
                    name=name,
                    position=position,
                    is_custom=True,
                )
                board.revision += 1
                board.save(update_fields=["revision", "updated_at"])
                AuditEvent.objects.create(
                    board=board,
                    board_revision=board.revision,
                    task=None,
                    actor=request.user,
                    action="create_list",
                    reason=str(payload.get("reason", ""))[:2000],
                    before={},
                    after=_column_payload(column),
                )
                return 201, {**_column_payload(column), "board_revision": board.revision}

        try:
            result = run_idempotent(
                actor=request.user,
                endpoint=f"/api/v1/boards/{board_id}/columns",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=create,
                authorize_replay=lambda: _authorize_board_member(request.user, board_id),
            )
            return Response(result.body, status=result.status)
        except BoardAdminError as exc:
            return _board_admin_error(exc)
        except IdempotencyError as exc:
            return _idempotency_error(exc)


class BoardColumnCommandView(APIView):
    def post(self, request, board_id, column_id, command):
        require_board_member(request.user, board_id)
        payload = request.data if isinstance(request.data, dict) else {}
        try:
            expected_revision = int(payload["expected_board_revision"])
        except (KeyError, TypeError, ValueError):
            return _board_admin_error(
                BoardAdminError(
                    "expected_revision_required",
                    "expected_board_revision is required.",
                    400,
                )
            )

        if command not in {"rename", "delete"}:
            return _board_admin_error(
                BoardAdminError("unknown_command", "Unknown list command.", 404)
            )

        def execute():
            with transaction.atomic():
                board = Board.objects.select_for_update().filter(pk=board_id, archived=False).first()
                if board is None:
                    raise BoardAdminError("not_found", "Board not found.", 404)
                require_board_member(request.user, board.id, for_update=True)
                if board.revision != expected_revision:
                    raise BoardAdminError(
                        "stale_state",
                        "The board changed since it was loaded.",
                        409,
                    )
                column = (
                    BoardColumn.objects.select_for_update()
                    .filter(pk=column_id, board=board)
                    .first()
                )
                if column is None or column.state == BoardColumn.State.REVIEW:
                    raise BoardAdminError("not_found", "List not found.", 404)

                before = _column_payload(column)
                if command == "rename":
                    name = str(payload.get("name", "")).strip()
                    if not name or len(name) > 100:
                        raise BoardAdminError(
                            "invalid_name",
                            "List name is required and must be 100 characters or less.",
                            400,
                        )
                    column.name = name
                    column.save(update_fields=["name"])
                    response_body: dict[str, object] = _column_payload(column)
                    action = "rename_list"
                else:
                    if not column.is_custom:
                        raise BoardAdminError(
                            "protected_list",
                            "Inbox, To Do, In Progress, Later, and Done cannot be deleted.",
                            409,
                        )
                    if column.tasks.exists():
                        raise BoardAdminError(
                            "list_not_empty",
                            "Move or delete every card in this list before deleting it.",
                            409,
                        )
                    response_body = {
                        "deleted": True,
                        "column_id": str(column.id),
                        "name": column.name,
                    }
                    action = "delete_list"
                    column.delete()

                board.revision += 1
                board.save(update_fields=["revision", "updated_at"])
                AuditEvent.objects.create(
                    board=board,
                    board_revision=board.revision,
                    task=None,
                    actor=request.user,
                    action=action,
                    reason=str(payload.get("reason", ""))[:2000],
                    before=before,
                    after=response_body,
                )
                response_body["board_revision"] = board.revision
                return 200, response_body

        try:
            result = run_idempotent(
                actor=request.user,
                endpoint=f"/api/v1/boards/{board_id}/columns/{column_id}/commands/{command}",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=execute,
                authorize_replay=lambda: _authorize_board_member(request.user, board_id),
            )
            return Response(result.body, status=result.status)
        except BoardAdminError as exc:
            return _board_admin_error(exc)
        except IdempotencyError as exc:
            return _idempotency_error(exc)


class BoardDeleteView(APIView):
    def post(self, request, board_id):
        require_site_admin(request.user)
        payload = request.data if isinstance(request.data, dict) else {}
        confirm_name = str(payload.get("confirm_name", ""))

        def execute():
            body = delete_board(
                actor=request.user,
                board_id=board_id,
                confirm_name=confirm_name,
            )
            return 200, body

        try:
            result = run_idempotent(
                actor=request.user,
                endpoint=f"/api/v1/boards/{board_id}/delete",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=execute,
                authorize_replay=lambda: require_site_admin(request.user),
            )
            return Response(result.body, status=result.status)
        except BoardDeletionError as exc:
            return Response(
                {
                    "code": exc.code,
                    "message": exc.message,
                    "field_errors": {},
                    "request_id": None,
                },
                status=exc.status,
            )
        except IdempotencyError as exc:
            return _idempotency_error(exc)


class BoardMembershipCollectionView(APIView):
    def get(self, request, board_id):
        require_board_manager_or_site_admin(request.user, board_id)
        board = Board.objects.filter(pk=board_id).first()
        if board is None:
            return _board_admin_error(BoardAdminError("not_found", "Board not found.", 404))
        rows = (
            BoardMembership.objects.filter(board=board)
            .select_related("user")
            .order_by("user__username")
        )
        return Response([_membership_payload(item) for item in rows])

    def post(self, request, board_id):
        require_board_manager_or_site_admin(request.user, board_id)
        payload = request.data if isinstance(request.data, dict) else {}
        user_id = payload.get("user_id")
        username = str(payload.get("username", "")).strip()
        if user_id:
            if not isinstance(user_id, str):
                return Response(
                    {
                        "code": "invalid_user",
                        "message": "user_id must be a valid UUID.",
                        "field_errors": {"user_id": ["Invalid UUID."]},
                        "request_id": None,
                    },
                    status=400,
                )
            try:
                user_id = str(UUID(user_id))
            except ValueError:
                return Response(
                    {
                        "code": "invalid_user",
                        "message": "user_id must be a valid UUID.",
                        "field_errors": {"user_id": ["Invalid UUID."]},
                        "request_id": None,
                    },
                    status=400,
                )
        elif not username:
            return Response(
                {
                    "code": "invalid_user",
                    "message": "Enter a username to share this board.",
                    "field_errors": {"username": ["Required."]},
                    "request_id": None,
                },
                status=400,
            )
        role = str(payload.get("role", BoardMembership.Role.MEMBER))
        if role not in BoardMembership.Role.values:
            return Response(
                {
                    "code": "invalid_role",
                    "message": "Role must be MEMBER or MANAGER.",
                    "field_errors": {"role": ["Invalid role."]},
                    "request_id": None,
                },
                status=400,
            )

        def create():
            with transaction.atomic():
                board = Board.objects.select_for_update().filter(pk=board_id).first()
                if board is None:
                    raise BoardAdminError("not_found", "Board not found.", 404)
                user_query = User.objects.select_for_update().filter(is_active=True)
                if user_id:
                    user = user_query.filter(pk=user_id).first()
                else:
                    user = user_query.filter(username__iexact=username).first()
                if user is None:
                    raise BoardAdminError(
                        "invalid_user",
                        "Membership requires an active user.",
                        400,
                    )
                existing = (
                    BoardMembership.objects.select_for_update()
                    .select_related("user")
                    .filter(board=board, user=user)
                    .first()
                )
                if existing is not None and existing.is_active:
                    raise BoardAdminError(
                        "membership_exists",
                        "User is already an active member of this board.",
                        409,
                    )
                before = _membership_payload(existing) if existing is not None else {}
                if existing is None:
                    membership = BoardMembership.objects.create(
                        board=board,
                        user=user,
                        role=role,
                        is_active=True,
                        created_by=request.user,
                    )
                else:
                    existing.role = role
                    existing.is_active = True
                    existing.save(update_fields=["role", "is_active"])
                    membership = existing
                membership = BoardMembership.objects.select_related("user").get(pk=membership.pk)
                after = _membership_payload(membership)
                _audit_board_membership(
                    board=board,
                    actor=request.user,
                    action="add_board_membership",
                    reason=str(payload.get("reason", "")),
                    before=before,
                    after=after,
                )
                return 201, after

        try:
            result = run_idempotent(
                actor=request.user,
                endpoint=f"/api/v1/boards/{board_id}/memberships",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=create,
                authorize_replay=lambda: _authorize_board_manager_or_admin(
                    request.user,
                    board_id,
                ),
            )
        except BoardAdminError as exc:
            return _board_admin_error(exc)
        except IdempotencyError as exc:
            return _idempotency_error(exc)
        return Response(result.body, status=result.status)


class BoardMembershipCommandView(APIView):
    COMMANDS = {"set_role", "remove"}

    def post(self, request, board_id, user_id, command: str):
        require_board_manager_or_site_admin(request.user, board_id)
        if command not in self.COMMANDS:
            return _board_admin_error(
                BoardAdminError(
                    "unknown_command",
                    f"Unknown membership command: {command}",
                    404,
                )
            )
        payload = request.data if isinstance(request.data, dict) else {}
        reason = str(payload.get("reason", "")).strip()
        if not reason:
            return _board_admin_error(
                BoardAdminError(
                    "reason_required",
                    "A reason is required for membership changes.",
                )
            )
        role = str(payload.get("role", ""))
        if command == "set_role" and role not in BoardMembership.Role.values:
            return _board_admin_error(
                BoardAdminError(
                    "invalid_role",
                    "Role must be MEMBER or MANAGER.",
                )
            )

        def execute():
            with transaction.atomic():
                board = Board.objects.select_for_update().filter(pk=board_id).first()
                if board is None:
                    raise BoardAdminError("not_found", "Board not found.", 404)
                membership = (
                    BoardMembership.objects.select_for_update()
                    .select_related("user")
                    .filter(board=board, user_id=user_id, is_active=True)
                    .first()
                )
                if membership is None:
                    raise BoardAdminError(
                        "membership_not_found",
                        "Active board membership not found.",
                        404,
                    )
                before = _membership_payload(membership)
                manager_count = _active_manager_count_for_update(board)
                if (
                    membership.role == BoardMembership.Role.MANAGER
                    and (
                        command == "remove"
                        or (command == "set_role" and role != BoardMembership.Role.MANAGER)
                    )
                    and manager_count <= 1
                ):
                    raise BoardAdminError(
                        "last_board_manager",
                        "The last active board manager cannot be removed or demoted.",
                        409,
                    )
                if command == "remove":
                    membership.is_active = False
                    membership.save(update_fields=["is_active"])
                    action = "remove_board_membership"
                else:
                    membership.role = role
                    membership.save(update_fields=["role"])
                    action = "change_board_membership_role"
                after = _membership_payload(membership)
                _audit_board_membership(
                    board=board,
                    actor=request.user,
                    action=action,
                    reason=reason,
                    before=before,
                    after=after,
                )
                return 200, after

        try:
            result = run_idempotent(
                actor=request.user,
                endpoint=(f"/api/v1/boards/{board_id}/memberships/{user_id}/commands/{command}"),
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=execute,
                authorize_replay=lambda: _authorize_board_manager_or_admin(
                    request.user,
                    board_id,
                ),
            )
        except BoardAdminError as exc:
            return _board_admin_error(exc)
        except IdempotencyError as exc:
            return _idempotency_error(exc)
        return Response(result.body, status=result.status)
