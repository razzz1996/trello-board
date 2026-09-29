from __future__ import annotations

from django.contrib.auth import logout
from django.http import JsonResponse


class SessionGenerationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            expected = request.session.get("auth_generation")
            if expected is None or expected != user.session_generation or not user.is_active:
                logout(request)
                if request.path.startswith("/api/"):
                    return JsonResponse(
                        {
                            "code": "session_revoked",
                            "message": "Session is no longer valid",
                            "field_errors": {},
                            "request_id": None,
                        },
                        status=401,
                    )
        return self.get_response(request)
