from __future__ import annotations

import mimetypes
from datetime import timedelta
from uuid import uuid4

from django.db import transaction
from django.db.models import Max
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from workitems.deletion import purge_task_dependencies
from workitems.models import AuditEvent, Task

from .models import Board, BoardColumn, BoardLabel, BoardPresence
from .permissions import require_board_member

BACKGROUND_KEYS = {
    "bubbles",
    "snow",
    "wave",
    "magic",
    "rainbow",
    "peach",
    "blossom",
    "earth",
    "alien",
    "wizard",
}
LABEL_COLORS = {"green", "yellow", "orange", "red", "purple", "blue"}
ARCHIVE_WINDOW_DAYS = 14
MAX_BACKGROUND_BYTES = 10 * 1024 * 1024


def _error(code: str, message: str, status: int = 400) -> Response:
    return Response(
        {"code": code, "message": message, "field_errors": {}, "request_id": None},
        status=status,
    )


def _expected_revision(request) -> int:
    try:
        return int(request.data.get("expected_board_revision"))
    except (TypeError, ValueError):
        raise ValueError from None


def _label_payload(label: BoardLabel) -> dict[str, object]:
    return {
        "id": str(label.id),
        "color": label.color,
        "name": label.name,
        "description": label.description,
        "position": label.position,
    }


def _bump(board: Board) -> None:
    board.revision += 1
    board.save(update_fields=["revision", "updated_at"])


def _audit(
    *,
    board: Board,
    actor,
    action: str,
    before: dict | None = None,
    after: dict | None = None,
    task: Task | None = None,
    reason: str = "",
) -> None:
    AuditEvent.objects.create(
        board=board,
        board_revision=board.revision,
        task=task,
        actor=actor,
        action=action,
        reason=reason[:2000],
        before=before or {},
        after=after or {},
    )


def _image_type(upload) -> tuple[str, str] | None:
    head = upload.read(16)
    upload.seek(0)
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


class BoardPresenceView(APIView):
    ACTIVE_WINDOW_SECONDS = 90

    def _payload(self, board_id, current_user_id):
        cutoff = timezone.now() - timedelta(seconds=self.ACTIVE_WINDOW_SECONDS)
        rows = (
            BoardPresence.objects.filter(
                board_id=board_id,
                last_seen_at__gte=cutoff,
                user__is_active=True,
                user__board_memberships__board_id=board_id,
                user__board_memberships__is_active=True,
            )
            .select_related("user")
            .distinct()
            .order_by("-last_seen_at")
        )
        return [
            {
                "id": str(row.user_id),
                "username": row.user.get_username(),
                "last_seen_at": row.last_seen_at.isoformat(),
                "is_current_user": row.user_id == current_user_id,
            }
            for row in rows
        ]

    def get(self, request, board_id):
        membership = require_board_member(request.user, board_id)
        return Response(
            {
                "active_window_seconds": self.ACTIVE_WINDOW_SECONDS,
                "users": self._payload(membership.board_id, request.user.id),
            }
        )

    def post(self, request, board_id):
        membership = require_board_member(request.user, board_id)
        BoardPresence.objects.update_or_create(
            board_id=membership.board_id,
            user=request.user,
            defaults={},
        )
        BoardPresence.objects.filter(
            board_id=membership.board_id,
            last_seen_at__lt=timezone.now() - timedelta(days=1),
        ).delete()
        return Response(
            {
                "active_window_seconds": self.ACTIVE_WINDOW_SECONDS,
                "users": self._payload(membership.board_id, request.user.id),
            }
        )


class BoardBackgroundView(APIView):
    def post(self, request, board_id):
        require_board_member(request.user, board_id)
        try:
            expected_revision = _expected_revision(request)
        except ValueError:
            return _error(
                "expected_revision_required",
                "expected_board_revision is required.",
            )

        upload = request.FILES.get("image")
        background_key = str(request.data.get("background_key", "")).strip().lower()
        if upload is None and background_key not in BACKGROUND_KEYS:
            return _error("invalid_background", "Choose an available board background.")

        if upload is not None:
            if upload.size > MAX_BACKGROUND_BYTES:
                return _error(
                    "background_too_large",
                    "Background images must be 10 MB or smaller.",
                )
            detected = _image_type(upload)
            if detected is None:
                return _error(
                    "invalid_background_image",
                    "Upload a PNG, JPEG, or WebP image.",
                )
            extension, _ = detected

        with transaction.atomic():
            board = Board.objects.select_for_update().filter(pk=board_id, archived=False).first()
            if board is None:
                raise Http404
            require_board_member(request.user, board.id, for_update=True)
            if board.revision != expected_revision:
                return _error(
                    "stale_state",
                    "The board changed since it was loaded. Reload and try again.",
                    409,
                )

            before = {
                "background_key": board.background_key,
                "has_background_image": bool(board.background_image),
            }
            old_name = board.background_image.name if board.background_image else ""

            if upload is not None:
                filename = f"{uuid4().hex}{extension}"
                board.background_image.save(filename, upload, save=False)
                board.background_key = ""
                action = "set_board_background_image"
            else:
                if board.background_image:
                    board.background_image = ""
                board.background_key = background_key
                action = "set_board_background_color"

            board.revision += 1
            board.save(
                update_fields=[
                    "background_key",
                    "background_image",
                    "revision",
                    "updated_at",
                ]
            )
            if old_name and old_name != board.background_image.name:
                board.background_image.storage.delete(old_name)

            after = {
                "background_key": board.background_key,
                "has_background_image": bool(board.background_image),
            }
            _audit(board=board, actor=request.user, action=action, before=before, after=after)
            return Response(
                {
                    **after,
                    "background_image_url": (
                        f"/api/v1/boards/{board.id}/background-image?rev={board.revision}"
                        if board.background_image
                        else None
                    ),
                    "board_revision": board.revision,
                }
            )


class BoardBackgroundImageView(APIView):
    def get(self, request, board_id):
        membership = require_board_member(request.user, board_id)
        board = Board.objects.filter(pk=membership.board_id, archived=False).first()
        if board is None or not board.background_image:
            raise Http404
        try:
            file_handle = board.background_image.open("rb")
        except FileNotFoundError as exc:
            raise Http404 from exc
        content_type = mimetypes.guess_type(board.background_image.name)[0] or "application/octet-stream"
        response = FileResponse(file_handle, content_type=content_type)
        response["Cache-Control"] = "private, max-age=3600"
        return response


class BoardLabelCollectionView(APIView):
    def get(self, request, board_id):
        membership = require_board_member(request.user, board_id)
        rows = BoardLabel.objects.filter(board_id=membership.board_id).order_by("position", "created_at")
        return Response([_label_payload(row) for row in rows])

    def post(self, request, board_id):
        require_board_member(request.user, board_id)
        payload = request.data if isinstance(request.data, dict) else {}
        color = str(payload.get("color", "")).strip().lower()
        name = str(payload.get("name", "")).strip()
        description = str(payload.get("description", "")).strip()
        if color not in LABEL_COLORS:
            return _error("invalid_label_color", "Choose an available label color.")
        if len(name) > 100 or len(description) > 500:
            return _error("invalid_label", "Label name or description is too long.")

        try:
            expected_revision = int(payload["expected_board_revision"])
        except (KeyError, TypeError, ValueError):
            return _error("expected_revision_required", "expected_board_revision is required.")

        with transaction.atomic():
            board = Board.objects.select_for_update().filter(pk=board_id, archived=False).first()
            if board is None:
                raise Http404
            require_board_member(request.user, board.id, for_update=True)
            if board.revision != expected_revision:
                return _error("stale_state", "The board changed since it was loaded.", 409)
            current_max = board.labels.aggregate(value=Max("position"))["value"]
            label = BoardLabel.objects.create(
                board=board,
                color=color,
                name=name,
                description=description,
                position=0 if current_max is None else int(current_max) + 1,
            )
            _bump(board)
            _audit(
                board=board,
                actor=request.user,
                action="create_board_label",
                after=_label_payload(label),
            )
            return Response({**_label_payload(label), "board_revision": board.revision}, status=201)


class BoardLabelCommandView(APIView):
    def post(self, request, board_id, label_id, command: str):
        require_board_member(request.user, board_id)
        if command not in {"update", "delete"}:
            return _error("unknown_command", "Unknown label command.", 404)
        payload = request.data if isinstance(request.data, dict) else {}
        try:
            expected_revision = int(payload["expected_board_revision"])
        except (KeyError, TypeError, ValueError):
            return _error("expected_revision_required", "expected_board_revision is required.")

        with transaction.atomic():
            board = Board.objects.select_for_update().filter(pk=board_id, archived=False).first()
            if board is None:
                raise Http404
            require_board_member(request.user, board.id, for_update=True)
            if board.revision != expected_revision:
                return _error("stale_state", "The board changed since it was loaded.", 409)
            label = BoardLabel.objects.select_for_update().filter(pk=label_id, board=board).first()
            if label is None:
                raise Http404
            before = _label_payload(label)

            if command == "delete":
                label.delete()
                _bump(board)
                _audit(
                    board=board,
                    actor=request.user,
                    action="delete_board_label",
                    before=before,
                    after={"deleted": True, "label_id": str(label_id)},
                )
                return Response({"deleted": True, "label_id": str(label_id), "board_revision": board.revision})

            color = str(payload.get("color", label.color)).strip().lower()
            name = str(payload.get("name", label.name)).strip()
            description = str(payload.get("description", label.description)).strip()
            if color not in LABEL_COLORS:
                return _error("invalid_label_color", "Choose an available label color.")
            if len(name) > 100 or len(description) > 500:
                return _error("invalid_label", "Label name or description is too long.")
            label.color = color
            label.name = name
            label.description = description
            label.save(update_fields=["color", "name", "description", "updated_at"])
            _bump(board)
            after = _label_payload(label)
            _audit(
                board=board,
                actor=request.user,
                action="update_board_label",
                before=before,
                after=after,
            )
            return Response({**after, "board_revision": board.revision})


def _event_message(event: AuditEvent, columns: dict[str, tuple[str, str]]) -> tuple[str, str]:
    actor = event.actor.get_username()
    task_title = event.task.title if event.task_id and event.task else ""
    before = event.before or {}
    after = event.after or {}
    action = event.action

    if action == "move_task":
        source_id = str(before.get("column_id", ""))
        target_id = str(after.get("column_id", ""))
        source_name, source_state = columns.get(source_id, ("another list", ""))
        target_name, target_state = columns.get(target_id, ("another list", ""))
        title = task_title or str(after.get("title") or before.get("title") or "a card")
        if target_state == BoardColumn.State.DONE and source_state != BoardColumn.State.DONE:
            return f"{actor} marked {title} complete", "activity"
        if source_state == BoardColumn.State.DONE and target_state != BoardColumn.State.DONE:
            return f"{actor} marked {title} incomplete", "activity"
        return f"{actor} moved {title} from {source_name} to {target_name}", "activity"
    if action == "add_comment":
        return f"{actor} commented on {task_title or 'a card'}", "comment"
    if action == "correct_comment":
        return f"{actor} edited a comment on {task_title or 'a card'}", "comment"
    if action == "create_task":
        column_id = str(after.get("column_id", ""))
        column_name = columns.get(column_id, ("a list", ""))[0]
        title = task_title or str(after.get("title") or "a card")
        return f"{actor} added {title} to {column_name}", "activity"
    if action == "add_board_membership":
        username = str(after.get("username") or "a user")
        return f"{username} joined this board (added by {actor})", "activity"
    if action == "remove_board_membership":
        username = str(before.get("username") or "a user")
        return f"{actor} removed {username} from this board", "activity"
    if action == "archive_task":
        title = task_title or str(before.get("title") or "a card")
        return f"{actor} archived {title}", "activity"
    if action == "restore_archived_task":
        title = task_title or str(after.get("title") or before.get("title") or "a card")
        return f"{actor} restored {title}", "activity"
    if action == "archive_list":
        return f"{actor} archived {str(before.get('name') or 'a list')}", "activity"
    if action == "restore_archived_list":
        return f"{actor} restored {str(after.get('name') or before.get('name') or 'a list')}", "activity"
    if action == "rename_board":
        return f"{actor} renamed this board to {str(after.get('name') or '')}", "activity"
    if action == "create_list":
        return f"{actor} added {str(after.get('name') or 'a list')} to this board", "activity"
    if action == "set_board_background_color":
        return f"{actor} changed the board background", "activity"
    if action == "set_board_background_image":
        return f"{actor} uploaded a board background", "activity"
    if action == "create_board_label":
        return f"{actor} created a board label", "activity"
    if action == "update_board_label":
        return f"{actor} updated a board label", "activity"
    if action == "delete_board_label":
        return f"{actor} deleted a board label", "activity"
    if action == "set_task_labels":
        return f"{actor} changed labels on {task_title or 'a card'}", "activity"
    if action == "edit_task":
        return f"{actor} updated {task_title or 'a card'}", "activity"
    if action == "set_checklist_item":
        return f"{actor} updated a checklist item on {task_title or 'a card'}", "activity"
    if action == "submit_result":
        return f"{actor} submitted {task_title or 'a card'} for review", "activity"
    if action == "review_submission":
        return f"{actor} reviewed {task_title or 'a card'}", "activity"
    readable = action.replace("_", " ")
    return f"{actor} {readable}", "activity"


class BoardActivityView(APIView):
    def get(self, request, board_id):
        membership = require_board_member(request.user, board_id)
        board = Board.objects.get(pk=membership.board_id)
        cutoff = timezone.now() - timedelta(days=ARCHIVE_WINDOW_DAYS)
        columns = {
            str(row.id): (row.name, row.state)
            for row in board.columns.all().only("id", "name", "state")
        }
        events = (
            board.audit_events.filter(created_at__gte=cutoff)
            .select_related("actor", "task")
            .order_by("-created_at")[:500]
        )
        rows = []
        for event in events:
            message, category = _event_message(event, columns)
            rows.append(
                {
                    "id": str(event.id),
                    "actor_id": str(event.actor_id),
                    "actor_username": event.actor.get_username(),
                    "action": event.action,
                    "category": category,
                    "message": message,
                    "task_id": str(event.task_id) if event.task_id else None,
                    "task_title": event.task.title if event.task_id and event.task else None,
                    "created_at": event.created_at.isoformat(),
                }
            )
        return Response({"days": ARCHIVE_WINDOW_DAYS, "activity": rows})


class BoardArchiveView(APIView):
    def get(self, request, board_id):
        membership = require_board_member(request.user, board_id)
        board = Board.objects.get(pk=membership.board_id)
        cutoff = timezone.now() - timedelta(days=ARCHIVE_WINDOW_DAYS)
        tasks = (
            Task.objects.filter(
                board=board,
                is_archived=True,
                archived_at__gte=cutoff,
            )
            .select_related("column", "current_owner")
            .order_by("-archived_at")[:300]
        )
        columns = (
            BoardColumn.objects.filter(
                board=board,
                is_archived=True,
                archived_at__gte=cutoff,
            )
            .order_by("-archived_at")[:100]
        )
        return Response(
            {
                "days": ARCHIVE_WINDOW_DAYS,
                "cards": [
                    {
                        "id": str(task.id),
                        "title": task.title,
                        "column_id": str(task.column_id),
                        "column_name": task.column.name,
                        "row_version": task.row_version,
                        "archived_at": task.archived_at.isoformat() if task.archived_at else None,
                        "owner_username": (
                            task.current_owner.get_username() if task.current_owner else None
                        ),
                    }
                    for task in tasks
                ],
                "lists": [
                    {
                        "id": str(column.id),
                        "name": column.name,
                        "archived_at": column.archived_at.isoformat() if column.archived_at else None,
                        "card_count": Task.objects.filter(column=column).count(),
                    }
                    for column in columns
                ],
            }
        )


class ArchivedTaskCommandView(APIView):
    def post(self, request, board_id, task_id, command: str):
        require_board_member(request.user, board_id)
        if command not in {"restore", "delete"}:
            return _error("unknown_command", "Unknown archived-card command.", 404)
        try:
            expected_revision = _expected_revision(request)
        except ValueError:
            return _error("expected_revision_required", "expected_board_revision is required.")

        with transaction.atomic():
            board = Board.objects.select_for_update().filter(pk=board_id, archived=False).first()
            if board is None:
                raise Http404
            require_board_member(request.user, board.id, for_update=True)
            if board.revision != expected_revision:
                return _error("stale_state", "The board changed since it was loaded.", 409)
            task = (
                Task.objects.select_for_update()
                .select_related("column")
                .filter(pk=task_id, board=board, is_archived=True)
                .first()
            )
            if task is None:
                raise Http404
            before = {
                "task_id": str(task.id),
                "title": task.title,
                "column_id": str(task.column_id),
                "row_version": task.row_version,
                "archived_at": task.archived_at.isoformat() if task.archived_at else None,
            }

            if command == "delete":
                title = task.title
                purge_task_dependencies([task.id])
                _bump(board)
                _audit(
                    board=board,
                    actor=request.user,
                    action="delete_archived_task",
                    before=before,
                    after={"deleted": True, "task_id": str(task_id), "title": title},
                )
                return Response(
                    {"deleted": True, "task_id": str(task_id), "board_revision": board.revision}
                )

            target = task.column
            if target.is_archived or target.state == BoardColumn.State.REVIEW:
                target = BoardColumn.objects.get(
                    board=board,
                    state=BoardColumn.State.BACKLOG,
                    is_archived=False,
                )
            max_position = (
                Task.objects.filter(column=target, is_cancelled=False, is_archived=False)
                .aggregate(value=Max("position"))["value"]
            )
            task.column = target
            task.position = 0 if max_position is None else int(max_position) + 1
            task.is_archived = False
            task.archived_at = None
            task.row_version += 1
            task.recurrence_generation += 1
            task.save(
                update_fields=[
                    "column",
                    "position",
                    "is_archived",
                    "archived_at",
                    "row_version",
                    "recurrence_generation",
                    "updated_at",
                ]
            )
            _bump(board)
            after = {
                "task_id": str(task.id),
                "title": task.title,
                "column_id": str(task.column_id),
                "row_version": task.row_version,
                "is_archived": False,
            }
            _audit(
                board=board,
                actor=request.user,
                action="restore_archived_task",
                before=before,
                after=after,
                task=task,
            )
            return Response({**after, "board_revision": board.revision})


class ArchivedListCommandView(APIView):
    def post(self, request, board_id, column_id, command: str):
        require_board_member(request.user, board_id)
        if command not in {"restore", "delete"}:
            return _error("unknown_command", "Unknown archived-list command.", 404)
        try:
            expected_revision = _expected_revision(request)
        except ValueError:
            return _error("expected_revision_required", "expected_board_revision is required.")

        with transaction.atomic():
            board = Board.objects.select_for_update().filter(pk=board_id, archived=False).first()
            if board is None:
                raise Http404
            require_board_member(request.user, board.id, for_update=True)
            if board.revision != expected_revision:
                return _error("stale_state", "The board changed since it was loaded.", 409)
            column = (
                BoardColumn.objects.select_for_update()
                .filter(pk=column_id, board=board, is_archived=True, is_custom=True)
                .first()
            )
            if column is None:
                raise Http404
            before = {
                "column_id": str(column.id),
                "name": column.name,
                "archived_at": column.archived_at.isoformat() if column.archived_at else None,
            }

            if command == "delete":
                task_ids = list(Task.objects.filter(column=column).values_list("id", flat=True))
                purge_task_dependencies(task_ids)
                name = column.name
                column.delete()
                _bump(board)
                _audit(
                    board=board,
                    actor=request.user,
                    action="delete_archived_list",
                    before=before,
                    after={"deleted": True, "column_id": str(column_id), "name": name},
                )
                return Response(
                    {"deleted": True, "column_id": str(column_id), "board_revision": board.revision}
                )

            active_count = (
                board.columns.filter(is_archived=False)
                .exclude(state=BoardColumn.State.REVIEW)
                .count()
            )
            if active_count >= 20:
                return _error(
                    "list_limit",
                    "Archive another list before restoring this one.",
                    409,
                )
            column.is_archived = False
            column.archived_at = None
            column.save(update_fields=["is_archived", "archived_at"])
            _bump(board)
            after = {
                "column_id": str(column.id),
                "name": column.name,
                "is_archived": False,
            }
            _audit(
                board=board,
                actor=request.user,
                action="restore_archived_list",
                before=before,
                after=after,
            )
            return Response({**after, "board_revision": board.revision})
