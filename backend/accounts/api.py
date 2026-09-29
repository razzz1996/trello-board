from __future__ import annotations

from typing import Any

from core.clock import now
from core.idempotency import IdempotencyError, run_idempotent
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.middleware.csrf import rotate_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AccountAuditEvent
from .throttle import clear_success, client_address, is_allowed, record_failure

User = get_user_model()


class AdminOperationError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        field_errors: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.field_errors = field_errors or {}


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
            user = User.objects.select_for_update().get(pk=request.user.pk)
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


def _require_admin(user: Any) -> None:
    if not user.is_authenticated or not user.is_active or not (user.is_staff or user.is_superuser):
        raise PermissionDenied("Administrator role required.")


def _admin_payload(user: Any) -> dict[str, Any]:
    return {
        **_user_payload(user),
        "is_active": user.is_active,
        "disabled_at": user.disabled_at.isoformat() if user.disabled_at else None,
        "slack_destination_generation": user.slack_destination_generation,
        "slack_verified": bool(
            user.slack_workspace_id and user.slack_member_id and user.slack_verified_at
        ),
    }


def _admin_count_for_update() -> int:
    ids = list(
        User.objects.select_for_update()
        .filter(is_active=True)
        .filter(Q(is_staff=True) | Q(is_superuser=True))
        .order_by("id")
        .values_list("id", flat=True)
    )
    return len(ids)


def _admin_error(code: str, message: str, status: int = 400, field_errors=None) -> Response:
    return Response(
        {
            "code": code,
            "message": message,
            "field_errors": field_errors or {},
            "request_id": None,
        },
        status=status,
    )


def _validate_temporary_password(value: Any, user: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError(["Temporary password is required."])
    validate_password(value, user=user)
    return value


def _audit_account(
    *,
    actor: Any,
    target: Any,
    action: str,
    reason: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    AccountAuditEvent.objects.create(
        actor=actor,
        target=target,
        action=action,
        reason=reason[:2000],
        before=before,
        after=after,
    )


class AdminUserCollectionView(APIView):
    def get(self, request):
        _require_admin(request.user)
        rows = User.objects.order_by("username")[:500]
        return Response([_admin_payload(user) for user in rows])

    def post(self, request):
        _require_admin(request.user)
        payload = request.data if isinstance(request.data, dict) else {}
        username = str(payload.get("username", "")).strip()
        is_admin = payload.get("is_admin", False)
        if not username or len(username) > 150:
            return _admin_error(
                "invalid_username",
                "Username is required and must be at most 150 characters.",
            )
        if not isinstance(is_admin, bool):
            return _admin_error(
                "invalid_admin_flag",
                "is_admin must be true or false.",
                field_errors={"is_admin": ["Boolean required."]},
            )

        candidate = User(username=username)
        try:
            password = _validate_temporary_password(
                payload.get("temporary_password"),
                candidate,
            )
        except ValidationError as exc:
            return _admin_error(
                "invalid_password",
                "Temporary password does not meet the password policy.",
                400,
                {"temporary_password": list(exc.messages)},
            )

        def create():
            with transaction.atomic():
                if User.objects.filter(username__iexact=username).exists():
                    raise AdminOperationError(
                        "username_exists",
                        "That username is already in use.",
                        409,
                    )
                user = User(
                    username=username,
                    is_staff=is_admin,
                    is_superuser=False,
                    is_active=True,
                    force_password_change=True,
                )
                user.set_password(password)
                user.save()
                after = _admin_payload(user)
                _audit_account(
                    actor=request.user,
                    target=user,
                    action="create_user",
                    reason=str(payload.get("reason", "")),
                    before={},
                    after=after,
                )
                return 201, after

        try:
            result = run_idempotent(
                actor=request.user,
                endpoint="/api/v1/admin/users",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=create,
                authorize_replay=lambda: _require_admin(request.user),
            )
        except AdminOperationError as exc:
            return _admin_error(exc.code, exc.message, exc.status, exc.field_errors)
        except IdempotencyError as exc:
            return _admin_error(exc.code, exc.message, exc.status)
        return Response(result.body, status=result.status)


class AdminUserCommandView(APIView):
    COMMANDS = {"reset_password", "disable", "enable", "set_admin"}

    def post(self, request, user_id, command: str):
        _require_admin(request.user)
        if command not in self.COMMANDS:
            return _admin_error(
                "unknown_command",
                f"Unknown account command: {command}",
                404,
            )
        payload = request.data if isinstance(request.data, dict) else {}

        def execute():
            body = self._execute(request.user, user_id, command, payload)
            return 200, body

        try:
            result = run_idempotent(
                actor=request.user,
                endpoint=f"/api/v1/admin/users/{user_id}/commands/{command}",
                key=request.headers.get("Idempotency-Key"),
                payload=dict(payload),
                handler=execute,
                authorize_replay=lambda: _require_admin(request.user),
            )
        except AdminOperationError as exc:
            return _admin_error(exc.code, exc.message, exc.status, exc.field_errors)
        except IdempotencyError as exc:
            return _admin_error(exc.code, exc.message, exc.status)
        return Response(result.body, status=result.status)

    def _execute(
        self,
        actor: Any,
        user_id: Any,
        command: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        reason = str(payload.get("reason", "")).strip()
        if not reason:
            raise AdminOperationError(
                "reason_required",
                "A reason is required for this account change.",
            )

        with transaction.atomic():
            admin_count = _admin_count_for_update() if command in {"disable", "set_admin"} else None
            try:
                target = User.objects.select_for_update().get(pk=user_id)
            except User.DoesNotExist as exc:
                raise AdminOperationError(
                    "not_found",
                    "User not found.",
                    404,
                ) from exc
            before = _admin_payload(target)

            if command == "reset_password":
                try:
                    password = _validate_temporary_password(
                        payload.get("temporary_password"),
                        target,
                    )
                except ValidationError as exc:
                    raise AdminOperationError(
                        "invalid_password",
                        "Temporary password does not meet the password policy.",
                        400,
                        {"temporary_password": list(exc.messages)},
                    ) from exc
                target.set_password(password)
                target.force_password_change = True
                target.session_generation += 1
                target.save(
                    update_fields=[
                        "password",
                        "force_password_change",
                        "session_generation",
                    ]
                )
            elif command == "disable":
                if (
                    target.is_active
                    and (target.is_staff or target.is_superuser)
                    and admin_count is not None
                    and admin_count <= 1
                ):
                    raise AdminOperationError(
                        "last_admin",
                        "The last active administrator cannot be disabled.",
                        409,
                    )
                target.is_active = False
                target.disabled_at = now()
                target.session_generation += 1
                target.slack_destination_generation += 1
                target.slack_verified_at = None
                target.slack_verified_by = None
                target.save(
                    update_fields=[
                        "is_active",
                        "disabled_at",
                        "session_generation",
                        "slack_destination_generation",
                        "slack_verified_at",
                        "slack_verified_by",
                    ]
                )
            elif command == "enable":
                target.is_active = True
                target.disabled_at = None
                target.session_generation += 1
                target.save(
                    update_fields=[
                        "is_active",
                        "disabled_at",
                        "session_generation",
                    ]
                )
            else:
                requested = payload.get("is_admin")
                if not isinstance(requested, bool):
                    raise AdminOperationError(
                        "invalid_admin_flag",
                        "is_admin must be true or false.",
                        400,
                        {"is_admin": ["Boolean required."]},
                    )
                if target.is_superuser and not requested:
                    raise AdminOperationError(
                        "superuser_protected",
                        "Superuser status requires the controlled local administration procedure.",
                        409,
                    )
                if (
                    not requested
                    and target.is_active
                    and (target.is_staff or target.is_superuser)
                    and admin_count is not None
                    and admin_count <= 1
                ):
                    raise AdminOperationError(
                        "last_admin",
                        "The last active administrator cannot be demoted.",
                        409,
                    )
                target.is_staff = requested
                target.save(update_fields=["is_staff"])

            after = _admin_payload(target)
            _audit_account(
                actor=actor,
                target=target,
                action=command,
                reason=reason,
                before=before,
                after=after,
            )
            return after
