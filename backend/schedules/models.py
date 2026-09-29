from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Schedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board = models.ForeignKey("boards.Board", on_delete=models.PROTECT, related_name="schedules")
    name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=64)
    active = models.BooleanField(default=False)
    generation = models.PositiveIntegerField(default=1)
    cursor_period_key = models.CharField(max_length=64, blank=True)
    current_revision = models.ForeignKey(
        "ScheduleRevision", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class ScheduleRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, related_name="revisions")
    revision = models.PositiveIntegerField()
    rule = models.JSONField(default=dict)
    template_fields = models.JSONField(default=dict)
    effective_base_period = models.CharField(max_length=64)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField(max_length=2000)
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["schedule", "revision"], name="uq_schedule_revision")
        ]
        ordering = ["schedule_id", "revision"]


class SchedulePause(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, related_name="pauses")
    start_base_date = models.DateField()
    end_base_date = models.DateField(null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(end_base_date__isnull=True)
                    | models.Q(end_base_date__gt=models.F("start_base_date"))
                ),
                name="schedule_pause_end_after_start",
            )
        ]


class Occurrence(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, related_name="occurrences")
    period_key = models.CharField(max_length=64)
    schedule_revision = models.ForeignKey(
        ScheduleRevision, on_delete=models.PROTECT, related_name="occurrences"
    )
    task = models.OneToOneField(
        "workitems.Task", on_delete=models.PROTECT, related_name="occurrence"
    )
    release_at = models.DateTimeField()
    due_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["schedule", "period_key"], name="uq_schedule_period")
        ]
        indexes = [models.Index(fields=["schedule", "period_key"])]
