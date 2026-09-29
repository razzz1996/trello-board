from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class RequestReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    endpoint = models.CharField(max_length=255)
    idempotency_key = models.CharField(max_length=128)
    canonical_request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["actor", "endpoint", "idempotency_key"],
                name="uq_actor_endpoint_idempotency",
            )
        ]
        indexes = [models.Index(fields=["created_at"])]
