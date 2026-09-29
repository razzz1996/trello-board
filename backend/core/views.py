from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET


@require_GET
def liveness(request):
    return JsonResponse({"status": "alive"})


@require_GET
@ensure_csrf_cookie
def csrf_bootstrap(request):
    return JsonResponse({"csrf_token": get_token(request)})


@require_GET
@login_required
def current_user(request):
    user = request.user
    return JsonResponse(
        {
            "id": str(user.id),
            "username": user.get_username(),
            "force_password_change": user.force_password_change,
            "is_admin": bool(user.is_staff or user.is_superuser),
            "session_generation": user.session_generation,
        }
    )
