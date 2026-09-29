from __future__ import annotations

from typing import Any

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.middleware.csrf import rotate_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .throttle import clear_success, client_address, is_allowed, record_failure


def _user_payload(user: Any) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "username": user.get_username(),
        "force_password_change": user.force_password_change,
        "is_admin": bool(user.is_staff or user.is_superuser),
        "session_generation": user.session_generation,
    }


@method_decorator(csrf_protect, name="dispatch")
class SessionLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        username = str(payload.get("username", "")).strip()
        password = payload.get("password")
        address = client_address(request)
        if not username or not isinstance(password, str):
            return Response(
                {
                    "code": "invalid_credentials",
                    "message": "Username or password is incorrect.",
                    "field_errors": {},
                    "request_id": None,
                },
                status=401,
            )

        if not is_allowed(username, address):
            return Response(
                {
                    "code": "login_throttled",
                    "message": "Sign-in is temporarily unavailable. Try again later or contact an administrator.",
                    "field_errors": {},
                    "request_id": None,
                },
                status=429,
            )

        user = authenticate(request, username=username, password=password)
        if user is None or not user.is_active:
            record_failure(username, address)
            return Response(
                {
                    "code": "invalid_credentials",
                    "message": "Username or password is incorrect.",
                    "field_errors": {},
                    "request_id": None,
                },
                status=401,
            )

        clear_success(username, address)
        login(request, user)
        request.session["auth_generation"] = user.session_generation
        rotate_token(request)
        return Response(_user_payload(user))


class SessionLogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=204)


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        current_password = payload.get("current_password")
        new_password = payload.get("new_password")
        if not isinstance(current_password, str) or not request.user.check_password(
            current_password
        ):
            return Response(
                {
                    "code": "invalid_current_password",
                    "message": "Current password is incorrect.",
                    "field_errors": {"current_password": ["Incorrect password."]},
                    "request_id": None,
                },
                status=400,
            )
        if not isinstance(new_password, str):
            return Response(
                {
                    "code": "invalid_password",
                    "message": "A new password is required.",
                    "field_errors": {"new_password": ["Required."]},
                    "request_id": None,
                },
                status=400,
            )
        try:
            validate_password(new_password, user=request.user)
        except ValidationError as exc:
            return Response(
                {
                    "code": "invalid_password",
                    "message": "The new password does not meet the password policy.",
                    "field_errors": {"new_password": list(exc.messages)},
                    "request_id": None,
                },
                status=400,
            )

        with transaction.atomic():
            user = type(request.user).objects.select_for_update().get(pk=request.user.pk)
            user.set_password(new_password)
            user.force_password_change = False
            user.session_generation += 1
            user.save(
                update_fields=[
                    "password",
                    "force_password_change",
                    "session_generation",
                ]
            )
        update_session_auth_hash(request, user)
        request.session["auth_generation"] = user.session_generation
        rotate_token(request)
        return Response(_user_payload(user))
