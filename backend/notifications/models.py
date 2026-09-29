from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Job(models.Model):
    class Status(models.TextChoices):
        READY = "READY", "Ready"
        LEASED = "LEASED", "Leased"
        SENDING = "SENDING", "Sending"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        RETRY_WAIT = "RETRY_WAIT", "Retry wait"
        FAILED = "FAILED", "Failed"
        SUPPRESSED = "SUPPRESSED", "Suppressed"
        UNKNOWN = "UNKNOWN", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    semantic_key = models.CharField(max_length=255, unique=True)
    job_type = models.CharField(max_length=64)
    run_after = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.READY)
    attempts = models.PositiveIntegerField(default=0)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict)
    generation = models.PositiveIntegerField(default=1)
    last_error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "run_after"]),
            models.Index(fields=["lease_expires_at"]),
        ]


class Notification(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        DRY_RUN = "DRY_RUN", "Dry run"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"
        SUPPRESSED = "SUPPRESSED", "Suppressed"
        UNKNOWN = "UNKNOWN", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    semantic_key = models.CharField(max_length=255, unique=True)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="notifications"
    )
    task = models.ForeignKey(
        "workitems.Task",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    report_snapshot = models.ForeignKey(
        "reports.ReportSnapshot",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    kind = models.CharField(max_length=64)
    scheduled_for = models.DateTimeField()
    observed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    destination_generation = models.PositiveIntegerField(default=1)
    message_preview = models.TextField(max_length=3000, blank=True)
    conversation_id = models.CharField(max_length=128, blank=True)
    message_ts = models.CharField(max_length=128, blank=True)
    attempt_uuid = models.UUIDField(null=True, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["recipient", "status", "scheduled_for"]),
            models.Index(fields=["task", "kind"]),
        ]


class SlackPilotApproval(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="slack_pilot_approvals",
    )
    destination_generation = models.PositiveIntegerField()
    sample_hash = models.CharField(max_length=64)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    approved_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "destination_generation"],
                name="uq_slack_pilot_recipient_generation",
            )
        ]
        indexes = [models.Index(fields=["recipient", "active"])]


class WorkerHeartbeat(models.Model):
    name = models.CharField(max_length=64, primary_key=True)
    last_seen_at = models.DateTimeField()
    process_id = models.PositiveIntegerField(null=True, blank=True)
    details = models.JSONField(default=dict)
