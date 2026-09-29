from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.db import connection, transaction

from .models import RequestReceipt


class IdempotencyError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True, slots=True)
class IdempotentResult:
    status: int
    body: dict[str, Any]
    replayed: bool


def canonical_request_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _advisory_key(actor_id: Any, endpoint: str, key: str) -> int:
    raw = f"{actor_id}|{endpoint}|{key}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big", signed=True)


def _json_safe(value: Any) -> Any:
    """Normalize response values to exactly what a JSON response/receipt can persist."""
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    )


def run_idempotent(
    *,
    actor,
    endpoint: str,
    key: str | None,
    payload: dict[str, Any],
    handler: Callable[[], tuple[int, dict[str, Any]]],
    authorize_replay: Callable[[], None] | None = None,
) -> IdempotentResult:
    if key is None or not key.strip():
        raise IdempotencyError(
            "idempotency_key_required",
            "Mutating requests require an Idempotency-Key header.",
            400,
        )
    key = key.strip()
    if len(key) > 128:
        raise IdempotencyError(
            "idempotency_key_invalid",
            "Idempotency-Key must be 128 characters or fewer.",
            400,
        )

    request_hash = canonical_request_hash(payload)
    lock_key = _advisory_key(actor.id, endpoint, key)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])

        existing = RequestReceipt.objects.filter(
            actor=actor,
            endpoint=endpoint,
            idempotency_key=key,
        ).first()
        if existing is not None:
            if existing.canonical_request_hash != request_hash:
                raise IdempotencyError(
                    "idempotency_mismatch",
                    "This Idempotency-Key was already used with different content.",
                    409,
                )
            if authorize_replay is not None:
                authorize_replay()
            return IdempotentResult(
                status=existing.response_status,
                body=existing.response_body,
                replayed=True,
            )

        receipt = RequestReceipt.objects.create(
            actor=actor,
            endpoint=endpoint,
            idempotency_key=key,
            canonical_request_hash=request_hash,
            response_status=0,
            response_body={},
        )
        status, body = handler()
        if status < 200 or status > 299:
            raise RuntimeError("Idempotent handlers may persist only successful responses.")
        normalized_body = _json_safe(body)
        if not isinstance(normalized_body, dict):
            raise RuntimeError("Idempotent handlers must return a JSON object response body.")
        receipt.response_status = status
        receipt.response_body = normalized_body
        receipt.save(update_fields=["response_status", "response_body"])
        return IdempotentResult(status=status, body=normalized_body, replayed=False)
