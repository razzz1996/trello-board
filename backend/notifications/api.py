from __future__ import annotations

from core.clock import now
from core.idempotency import IdempotencyError, run_idempotent
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification


def _row(item: Notification) -> dict:
    return {
        "id": str(item.id),
        "kind": item.kind,
        "task_id": str(item.task_id) if item.task_id else None,
        "report_id": str(item.report_snapshot_id) if item.report_snapshot_id else None,
        "scheduled_for": item.scheduled_for.isoformat(),
        "observed_at": item.observed_at.isoformat() if item.observed_at else None,
        "status": item.status,
        "message": item.message_preview,
        "read_at": item.read_at.isoformat() if item.read_at else None,
    }


class NotificationInboxView(APIView):
    def get(self, request):
        unread = request.query_params.get("unread")
        qs = Notification.objects.filter(recipient=request.user).order_by("-created_at")
        if unread == "1":
            qs = qs.filter(read_at__isnull=True)
        try:
            limit = min(max(int(request.query_params.get("limit", "100")), 1), 100)
        except ValueError:
            return Response(
                {
                    "code": "invalid_limit",
                    "message": "limit must be an integer.",
                    "field_errors": {},
                    "request_id": None,
                },
                status=400,
            )
        return Response([_row(item) for item in qs[:limit]])


class NotificationReadView(APIView):
    def post(self, request, notification_id):
        def authorize_replay() -> None:
            if not Notification.objects.filter(pk=notification_id, recipient=request.user).exists():
                from django.http import Http404

                raise Http404

        def mark_read():
            item = Notification.objects.filter(pk=notification_id, recipient=request.user).first()
            if item is None:
                from django.http import Http404

                raise Http404
            if item.read_at is None:
                item.read_at = now()
                item.save(update_fields=["read_at"])
            return 200, _row(item)

        try:
            result = run_idempotent(
                actor=request.user,
                endpoint=f"/api/v1/notifications/{notification_id}/read",
                key=request.headers.get("Idempotency-Key"),
                payload={},
                handler=mark_read,
                authorize_replay=authorize_replay,
            )
            return Response(result.body, status=result.status)
        except IdempotencyError as exc:
            return Response(
                {
                    "code": exc.code,
                    "message": exc.message,
                    "field_errors": {},
                    "request_id": None,
                },
                status=exc.status,
            )
