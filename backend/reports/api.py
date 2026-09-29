from __future__ import annotations

from datetime import date

from core.idempotency import IdempotencyError, run_idempotent
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ReportSnapshot
from .services import create_snapshot, manager_board_ids, snapshot_scope_authorized


def _row(snapshot: ReportSnapshot, *, include_rows: bool) -> dict:
    value = {
        "id": str(snapshot.id),
        "report_date": snapshot.report_date.isoformat(),
        "scheduled_for": snapshot.scheduled_for.isoformat(),
        "observation_started_at": snapshot.observation_started_at.isoformat(),
        "generated_at": snapshot.generated_at.isoformat(),
        "timezone": snapshot.timezone,
        "definition_version": snapshot.definition_version,
        "generation": snapshot.generation,
        "delayed": snapshot.delayed,
        "metrics": snapshot.metrics,
        "scope_board_ids": snapshot.scope_board_ids,
    }
    if include_rows:
        value["rows"] = snapshot.rows
    return value


class ReportCollectionView(APIView):
    def get(self, request):
        snapshots = ReportSnapshot.objects.filter(recipient=request.user).order_by(
            "-report_date", "-generated_at"
        )[:100]
        visible = [
            _row(item, include_rows=False)
            for item in snapshots
            if snapshot_scope_authorized(item, request.user)
        ]
        return Response(visible)

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        raw_date = payload.get("report_date")
        try:
            report_date = date.fromisoformat(str(raw_date)) if raw_date else date.today()
        except ValueError:
            return Response(
                {
                    "code": "invalid_date",
                    "message": "report_date must be an ISO date.",
                    "field_errors": {},
                    "request_id": None,
                },
                status=400,
            )

        def authorize_replay() -> None:
            if not manager_board_ids(request.user):
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("Board manager role required.")

        def create():
            snapshot = create_snapshot(recipient=request.user, report_date=report_date)
            if snapshot is None:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("Board manager role required.")
            return 201, _row(snapshot, include_rows=True)

        try:
            result = run_idempotent(
                actor=request.user,
                endpoint="/api/v1/reports",
                key=request.headers.get("Idempotency-Key"),
                payload={"report_date": report_date.isoformat()},
                handler=create,
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


class ReportDetailView(APIView):
    def get(self, request, report_id):
        snapshot = ReportSnapshot.objects.filter(pk=report_id, recipient=request.user).first()
        if snapshot is None or not snapshot_scope_authorized(snapshot, request.user):
            from django.http import Http404

            raise Http404
        return Response(_row(snapshot, include_rows=True))
