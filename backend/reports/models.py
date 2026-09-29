from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class ReportSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="report_snapshots"
    )
    report_date = models.DateField()
    scheduled_for = models.DateTimeField()
    observation_started_at = models.DateTimeField()
    generated_at = models.DateTimeField()
    timezone = models.CharField(max_length=64)
    scope_board_ids = models.JSONField(default=list)
    definition_version = models.PositiveIntegerField(default=1)
    generation = models.PositiveIntegerField(default=1)
    rows = models.JSONField(default=list)
    metrics = models.JSONField(default=dict)
    delayed = models.BooleanField(default=False)
    revised_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="revisions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["recipient", "report_date", "generated_at"])]
