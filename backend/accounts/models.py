from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    force_password_change = models.BooleanField(default=True)
    session_generation = models.PositiveIntegerField(default=1)
    slack_workspace_id = models.CharField(max_length=64, null=True, blank=True)
    slack_member_id = models.CharField(max_length=64, null=True, blank=True)
    slack_destination_generation = models.PositiveIntegerField(default=1)
    slack_verified_at = models.DateTimeField(null=True, blank=True)
    slack_verified_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    disabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["is_active", "username"])]


class AccountAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="account_audit_events",
    )
    target = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="account_audit_history",
    )
    action = models.CharField(max_length=100)
    reason = models.TextField(max_length=2000, blank=True)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["target", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
        ]


class LoginThrottle(models.Model):
    class Scope(models.TextChoices):
        ACCOUNT = "ACCOUNT", "Account"
        ADDRESS = "ADDRESS", "Address"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=16, choices=Scope.choices)
    key_hash = models.CharField(max_length=64)
    failure_count = models.PositiveSmallIntegerField(default=0)
    window_started_at = models.DateTimeField()
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "key_hash"],
                name="uq_login_throttle_scope_key",
            )
        ]
        indexes = [models.Index(fields=["scope", "locked_until"])]
