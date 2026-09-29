from __future__ import annotations

from datetime import date
from typing import Any

from boards.permissions import require_board_manager, require_board_member, visible_boards
from core.idempotency import IdempotencyError, run_idempotent
from django.http import Http404
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Schedule


def _error(code: str, message: str, status: int) -> Response:
    return Response(
        {"code": code, "message": message, "field_errors": {}, "request_id": None},
        status=status,
    )


def _date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise services.ScheduleError("invalid_date", f"{field} must be an ISO date.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise services.ScheduleError("invalid_date", f"{field} must be an ISO date.") from exc


def _schedule_for_replay(user, schedule_id, manager: bool) -> None:
    row = Schedule.objects.only("board_id").filter(pk=schedule_id).first()
    if row is None:
        raise Http404
    if manager:
        require_board_manager(user, row.board_id)
    else:
        require_board_member(user, row.board_id)


class ScheduleCollectionView(APIView):
    def get(self, request):
        qs = Schedule.objects.filter(board__in=visible_boards(request.user)).select_related(
            "current_revision"
        )
        board_id = request.query_params.get("board")
        if board_id:
            require_board_member(request.user, board_id)
            qs = qs.filter(board_id=board_id)
        return Response([services.serialize_schedule(item) for item in qs.order_by("name")])

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        try:
            board_id = payload["board_id"]

            def create():
                schedule = services.create_draft(
                    actor=request.user,
                    board_id=board_id,
                    name=str(payload.get("name", "")),
                    timezone_name=str(payload.get("timezone", "")),
                )
                return 201, services.serialize_schedule(schedule)

            def authorize_replay() -> None:
                require_board_member(request.user, board_id)

            result = run_idempotent(
                actor=request.user,
                endpoint="/api/v1/schedules",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=create,
                authorize_replay=authorize_replay,
            )
            return Response(result.body, status=result.status)
        except KeyError:
            return _error("board_required", "board_id is required.", 400)
        except services.ScheduleError as exc:
            return _error(exc.code, exc.message, exc.status)
        except IdempotencyError as exc:
            return _error(exc.code, exc.message, exc.status)


class SchedulePreviewView(APIView):
    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        try:
            board_id = payload["board_id"]
            rule = payload.get("rule")
            if not isinstance(rule, dict):
                raise services.ScheduleError("invalid_rule", "rule must be an object.")
            pauses = payload.get("pauses")
            if pauses is not None and not isinstance(pauses, list):
                raise services.ScheduleError("invalid_pause", "pauses must be a list.")
            after = _date(str(payload.get("after", date.today().isoformat())), "after")
            rows = services.preview_rule(
                actor=request.user,
                board_id=board_id,
                rule=rule,
                after=after,
                pauses=pauses,
            )
            return Response({"occurrences": rows})
        except KeyError:
            return _error("board_required", "board_id is required.", 400)
        except services.ScheduleError as exc:
            return _error(exc.code, exc.message, exc.status)


class ScheduleCommandView(APIView):
    MANAGER_COMMANDS = {"publish", "revise", "pause", "resume"}

    def post(self, request, schedule_id, command: str):
        if command not in self.MANAGER_COMMANDS:
            return _error("unknown_command", f"Unknown schedule command: {command}", 404)
        payload = request.data if isinstance(request.data, dict) else {}

        try:

            def execute():
                schedule = self._dispatch(request.user, schedule_id, command, payload)
                return 200, services.serialize_schedule(schedule)

            result = run_idempotent(
                actor=request.user,
                endpoint=f"/api/v1/schedules/{schedule_id}/commands/{command}",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=execute,
                authorize_replay=lambda: _schedule_for_replay(
                    request.user, schedule_id, manager=True
                ),
            )
            return Response(result.body, status=result.status)
        except services.ScheduleError as exc:
            return _error(exc.code, exc.message, exc.status)
        except IdempotencyError as exc:
            return _error(exc.code, exc.message, exc.status)

    def _dispatch(self, user, schedule_id, command: str, payload: dict[str, Any]) -> Schedule:
        if command in {"publish", "revise"}:
            rule = payload.get("rule")
            template = payload.get("template_fields")
            if not isinstance(rule, dict) or not isinstance(template, dict):
                raise services.ScheduleError(
                    "invalid_schedule",
                    "rule and template_fields must be objects.",
                )
            kwargs = {
                "actor": user,
                "schedule_id": schedule_id,
                "rule": rule,
                "template_fields": template,
                "effective_base_period": str(payload.get("effective_base_period", "")).strip(),
                "reason": str(payload.get("reason", "")),
            }
            if not kwargs["effective_base_period"]:
                raise services.ScheduleError(
                    "effective_period_required",
                    "effective_base_period is required.",
                )
            return services.publish(**kwargs) if command == "publish" else services.revise(**kwargs)
        if command == "pause":
            return services.pause(
                actor=user,
                schedule_id=schedule_id,
                start_base_date=_date(payload.get("start_base_date"), "start_base_date"),
                reason=str(payload.get("reason", "")),
            )
        if command == "resume":
            return services.resume(
                actor=user,
                schedule_id=schedule_id,
                end_base_date=_date(payload.get("end_base_date"), "end_base_date"),
                reason=str(payload.get("reason", "")),
            )
        raise services.ScheduleError("unknown_command", "Unknown schedule command.", 404)
