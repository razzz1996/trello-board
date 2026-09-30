from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from ipaddress import IPv6Address, ip_address

from core.clock import now
from django.conf import settings
from django.db import transaction

from .models import LoginThrottle

WINDOW = timedelta(minutes=15)
LOCK_DURATION = timedelta(minutes=15)
ACCOUNT_MAX_FAILURES = 5
ADDRESS_MAX_FAILURES = 50


def _hash(scope: str, value: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"{scope}|{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _normalize_address(value: str) -> str | None:
    candidate = value.strip()
    if not candidate:
        return None
    try:
        parsed = ip_address(candidate)
    except ValueError:
        return None
    if isinstance(parsed, IPv6Address) and parsed.ipv4_mapped is not None:
        return str(parsed.ipv4_mapped)
    return str(parsed)


def client_address(request) -> str:
    remote = _normalize_address(request.META.get("REMOTE_ADDR", ""))
    if remote in {"127.0.0.1", "::1"}:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            # Vite/Caddy is the one trusted local proxy. It appends the actual
            # peer address, so use the final value and ignore client-supplied
            # entries that may precede it.
            client = _normalize_address(forwarded.rsplit(",", 1)[-1])
            if client is not None:
                return client
    return remote or "unknown"


def _keys(username: str, address: str) -> list[tuple[str, str]]:
    return [
        (LoginThrottle.Scope.ACCOUNT, _hash("account", username.casefold())),
        (LoginThrottle.Scope.ADDRESS, _hash("address", address)),
    ]


def _failure_limit(scope: str) -> int:
    if scope == LoginThrottle.Scope.ACCOUNT:
        return ACCOUNT_MAX_FAILURES
    return ADDRESS_MAX_FAILURES


def is_allowed(username: str, address: str) -> bool:
    observed_at = now()
    hashes = _keys(username, address)
    for scope, key_hash in hashes:
        row = LoginThrottle.objects.filter(scope=scope, key_hash=key_hash).first()
        if row is not None and row.locked_until is not None and row.locked_until > observed_at:
            return False
    return True


def record_failure(username: str, address: str) -> None:
    observed_at = now()
    with transaction.atomic():
        for scope, key_hash in _keys(username, address):
            row, _ = LoginThrottle.objects.select_for_update().get_or_create(
                scope=scope,
                key_hash=key_hash,
                defaults={"window_started_at": observed_at},
            )
            if observed_at - row.window_started_at >= WINDOW:
                row.window_started_at = observed_at
                row.failure_count = 0
                row.locked_until = None
            row.failure_count += 1
            if row.failure_count >= _failure_limit(scope):
                row.locked_until = observed_at + LOCK_DURATION
            row.save(
                update_fields=[
                    "window_started_at",
                    "failure_count",
                    "locked_until",
                    "updated_at",
                ]
            )


def clear_success(username: str, address: str) -> None:
    del address  # Address-level protection is shared and must not be reset by one user.
    LoginThrottle.objects.filter(
        scope=LoginThrottle.Scope.ACCOUNT,
        key_hash=_hash("account", username.casefold()),
    ).delete()
