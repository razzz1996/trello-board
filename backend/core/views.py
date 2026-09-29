from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET
from notifications.models import Job, WorkerHeartbeat


@require_GET
def liveness(request):
    return JsonResponse({"status": "alive"})


@require_GET
def readiness(request):
    components: dict[str, dict[str, object]] = {}
    ready = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
        db_ok = bool(row and row[0] == 1)
    except Exception as exc:
        db_ok = False
        components["database"] = {
            "ok": False,
            "error": type(exc).__name__,
        }
    else:
        components["database"] = {"ok": db_ok}
    ready = ready and db_ok

    now = timezone.now()
    freshness = timedelta(seconds=max(int(settings.DEPLOYMENT["worker_tick_seconds"]) * 4, 60))
    heartbeat_rows = (
        {row.name: row for row in WorkerHeartbeat.objects.filter(name__in=["scheduler", "worker"])}
        if db_ok
        else {}
    )

    for name in ("scheduler", "worker"):
        row = heartbeat_rows.get(name)
        fresh = bool(row and now - row.last_seen_at <= freshness)
        components[name] = {
            "ok": fresh,
            "last_seen_at": row.last_seen_at.isoformat() if row else None,
        }
        if settings.DEPLOYMENT["environment"] == "pilot":
            ready = ready and fresh

    return JsonResponse(
        {
            "status": "ready" if ready else "not_ready",
            "environment": settings.DEPLOYMENT["environment"],
            "components": components,
        },
        status=200 if ready else 503,
    )


@require_GET
def health_detail(request):
    user = request.user
    if not user.is_authenticated or not user.is_active or not (user.is_staff or user.is_superuser):
        return JsonResponse(
            {
                "code": "forbidden",
                "message": "Administrator access is required.",
                "field_errors": {},
                "request_id": None,
            },
            status=403,
        )

    observed_at = timezone.now()
    warnings: list[str] = []
    heartbeat_data: dict[str, dict[str, object]] = {}
    for name in ("scheduler", "worker"):
        heartbeat = WorkerHeartbeat.objects.filter(name=name).first()
        age_seconds = (
            max(0.0, (observed_at - heartbeat.last_seen_at).total_seconds()) if heartbeat else None
        )
        stale = age_seconds is None or age_seconds > 90
        if stale:
            warnings.append(f"{name}_heartbeat_stale")
        heartbeat_data[name] = {
            "last_seen_at": heartbeat.last_seen_at.isoformat() if heartbeat else None,
            "age_seconds": round(age_seconds, 2) if age_seconds is not None else None,
            "stale": stale,
        }

    oldest_ready = (
        Job.objects.filter(
            status__in=[Job.Status.READY, Job.Status.RETRY_WAIT],
            run_after__lte=observed_at,
        )
        .order_by("run_after")
        .first()
    )
    ready_age_seconds = (
        max(0.0, (observed_at - oldest_ready.run_after).total_seconds()) if oldest_ready else 0.0
    )
    if ready_age_seconds > 300:
        warnings.append("ready_job_age_high")

    usage = shutil.disk_usage(settings.PROJECT_ROOT)
    free_percent = (usage.free * 100.0 / usage.total) if usage.total else 0.0
    if free_percent < 10.0:
        warnings.append("disk_free_low")

    backup_target = settings.DEPLOYMENT.get("backup_target")
    backup_age_hours = None
    backup_status = "not_configured"
    if backup_target:
        target = Path(str(backup_target))
        try:
            candidates = list(target.glob("productivity_*.dump")) if target.is_dir() else []
        except OSError:
            candidates = []
        if candidates:
            latest = max(candidates, key=lambda item: item.stat().st_mtime)
            modified = datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC)
            backup_age_hours = max(
                0.0,
                (observed_at.astimezone(UTC) - modified).total_seconds() / 3600,
            )
            backup_status = "ok" if backup_age_hours <= 26 else "stale"
        else:
            backup_status = "missing"
    if backup_status != "ok":
        warnings.append(f"backup_{backup_status}")

    return JsonResponse(
        {
            "observed_at": observed_at.isoformat(),
            "heartbeats": heartbeat_data,
            "queue": {
                "oldest_ready_age_seconds": round(ready_age_seconds, 2),
                "failed": Job.objects.filter(status=Job.Status.FAILED).count(),
                "unknown": Job.objects.filter(status=Job.Status.UNKNOWN).count(),
            },
            "disk": {
                "free_bytes": usage.free,
                "total_bytes": usage.total,
                "free_percent": round(free_percent, 2),
            },
            "backup": {
                "status": backup_status,
                "age_hours": round(backup_age_hours, 2) if backup_age_hours is not None else None,
            },
            "warnings": warnings,
        }
    )


@require_GET
@ensure_csrf_cookie
def csrf_bootstrap(request):
    return JsonResponse({"csrf_token": get_token(request)})


@require_GET
def current_user(request):
    user = request.user
    if not user.is_authenticated or not user.is_active:
        return JsonResponse(
            {
                "code": "authentication_required",
                "message": "Authentication is required.",
                "field_errors": {},
                "request_id": None,
            },
            status=401,
        )
    return JsonResponse(
        {
            "id": str(user.id),
            "username": user.get_username(),
            "force_password_change": user.force_password_change,
            "is_admin": bool(user.is_staff or user.is_superuser),
            "session_generation": user.session_generation,
        }
    )
