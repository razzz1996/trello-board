from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import LoginThrottle

WINDOW = timedelta(minutes=15)
LOCK_DURATION = timedelta(minutes=15)
MAX_FAILURES = 5


def _hash(scope: str, value: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"{scope}|{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def client_address(request) -> str:
    remote = request.META.get("REMOTE_ADDR", "")
    if remote in {"127.0.0.1", "::1"}:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return remote or "unknown"


def _keys(username: str, address: str) -> list[tuple[str, str]]:
    return [
        (LoginThrottle.Scope.ACCOUNT, _hash("account", username.casefold())),
        (LoginThrottle.Scope.ADDRESS, _hash("address", address)),
    ]


def is_allowed(username: str, address: str) -> bool:
    now = timezone.now()
    hashes = _keys(username, address)
    for scope, key_hash in hashes:
        row = LoginThrottle.objects.filter(scope=scope, key_hash=key_hash).first()
        if row is not None and row.locked_until is not None and row.locked_until > now:
            return False
    return True


def record_failure(username: str, address: str) -> None:
    now = timezone.now()
    with transaction.atomic():
        for scope, key_hash in _keys(username, address):
            row, _ = LoginThrottle.objects.select_for_update().get_or_create(
                scope=scope,
                key_hash=key_hash,
                defaults={"window_started_at": now},
            )
            if now - row.window_started_at >= WINDOW:
                row.window_started_at = now
                row.failure_count = 0
                row.locked_until = None
            row.failure_count += 1
            if row.failure_count >= MAX_FAILURES:
                row.locked_until = now + LOCK_DURATION
            row.save(
                update_fields=[
                    "window_started_at",
                    "failure_count",
                    "locked_until",
                    "updated_at",
                ]
            )


def clear_success(username: str, address: str) -> None:
    pairs = _keys(username, address)
    for scope, key_hash in pairs:
        LoginThrottle.objects.filter(scope=scope, key_hash=key_hash).delete()
