from __future__ import annotations

from django.conf import settings
from django.contrib.auth import logout
from django.http import JsonResponse
from django.utils import timezone


class SessionGenerationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def _reject(self, request, *, code: str, message: str):
        logout(request)
        if request.path.startswith("/api/"):
            return JsonResponse(
                {
                    "code": code,
                    "message": message,
                    "field_errors": {},
                    "request_id": None,
                },
                status=401,
            )
        return self.get_response(request)

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            expected = request.session.get("auth_generation")
            if expected is None or expected != user.session_generation or not user.is_active:
                return self._reject(
                    request,
                    code="session_revoked",
                    message="Session is no longer valid",
                )

            started_at = request.session.get("auth_started_at")
            now_ts = timezone.now().timestamp()
            if started_at is None:
                # Preserve existing sessions across this deployment and start the
                # absolute lifetime from their first post-upgrade authenticated request.
                request.session["auth_started_at"] = now_ts
            else:
                try:
                    age = now_ts - float(started_at)
                except (TypeError, ValueError):
                    age = settings.PRODUCTIVITY_SESSION_ABSOLUTE_AGE + 1
                if age > settings.PRODUCTIVITY_SESSION_ABSOLUTE_AGE:
                    return self._reject(
                        request,
                        code="session_expired",
                        message="Session reached its maximum lifetime. Please sign in again.",
                    )
        return self.get_response(request)
