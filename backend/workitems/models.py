from __future__ import annotations

import uuid

from core.clock import now as clock_now
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class Task(models.Model):
    class Recurrence(models.TextChoices):
        NONE = "NONE", "Does not repeat"
        DAILY = "DAILY", "Daily"
        WEEKLY = "WEEKLY", "Weekly"
        MONTHLY = "MONTHLY", "Monthly"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board = models.ForeignKey("boards.Board", on_delete=models.PROTECT, related_name="tasks")
    column = models.ForeignKey("boards.BoardColumn", on_delete=models.PROTECT, related_name="tasks")
    title = models.CharField(max_length=200)
    description = models.TextField(max_length=20000, blank=True)
    priority = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(3)], default=1
    )
    current_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="owned_tasks",
    )
    original_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="original_tasks",
    )
    row_version = models.PositiveBigIntegerField(default=1)
    position = models.PositiveIntegerField(default=0)
    draft_due_at = models.DateTimeField(null=True, blank=True)
    draft_acceptance_criteria = models.TextField(max_length=10000, blank=True)
    recurrence_frequency = models.CharField(
        max_length=16,
        choices=Recurrence.choices,
        default=Recurrence.NONE,
    )
    recurrence_next_at = models.DateTimeField(null=True, blank=True)
    recurrence_last_triggered_at = models.DateTimeField(null=True, blank=True)
    recurrence_anchor_day = models.PositiveSmallIntegerField(null=True, blank=True)
    recurrence_generation = models.PositiveIntegerField(default=1)
    committed_at = models.DateTimeField(null=True, blank=True)
    current_commitment = models.ForeignKey(
        "CommitmentRevision", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    is_cancelled = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_tasks"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(priority__gte=1, priority__lte=3), name="task_priority_1_3"
            ),
            models.CheckConstraint(condition=Q(row_version__gte=1), name="task_version_positive"),
            models.CheckConstraint(
                condition=Q(recurrence_generation__gte=1),
                name="task_recurrence_generation_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(recurrence_anchor_day__isnull=True)
                    | Q(recurrence_anchor_day__gte=1, recurrence_anchor_day__lte=31)
                ),
                name="task_recurrence_anchor_day_1_31",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        recurrence_frequency="NONE",
                        recurrence_next_at__isnull=True,
                    )
                    | (~Q(recurrence_frequency="NONE") & Q(recurrence_next_at__isnull=False))
                ),
                name="task_recurrence_configuration_valid",
            ),
            models.UniqueConstraint(
                fields=["column", "position"],
                condition=Q(is_cancelled=False, is_archived=False),
                name="uq_active_task_position",
            ),
        ]
        indexes = [
            models.Index(fields=["board", "column"]),
            models.Index(fields=["current_owner", "is_cancelled", "is_archived"]),
            models.Index(fields=["priority", "is_cancelled", "is_archived"]),
            models.Index(
                fields=["recurrence_frequency", "recurrence_next_at"],
                name="workitems_recurrence_due_idx",
            ),
        ]


class CommitmentRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="commitments")
    revision = models.PositiveIntegerField()
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    due_at = models.DateTimeField()
    priority = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(3)]
    )
    acceptance_criteria = models.TextField(max_length=10000)
    required_checklist_snapshot = models.JSONField(default=list)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task", "revision"], name="uq_task_commitment_revision"
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="commitment_revision_positive"
            ),
            models.CheckConstraint(
                condition=Q(priority__gte=1, priority__lte=3), name="commitment_priority_1_3"
            ),
        ]
        ordering = ["task_id", "revision"]


class ChecklistItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="checklist_items")
    text = models.CharField(max_length=500)
    required = models.BooleanField(default=False)
    position = models.PositiveIntegerField()
    checked = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["task", "position"], name="uq_task_checklist_position")
        ]
        ordering = ["position"]


class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField(max_length=10000)
    created_at = models.DateTimeField(auto_now_add=True)
    corrected_at = models.DateTimeField(null=True, blank=True)


class CommentEditHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="history")
    editor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    previous_body = models.TextField(max_length=10000)
    replacement_body = models.TextField(max_length=10000)
    edited_at = models.DateTimeField(auto_now_add=True)


class Submission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="submissions")
    commitment = models.ForeignKey(
        CommitmentRevision, on_delete=models.PROTECT, related_name="submissions"
    )
    accountable_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    submitting_actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    result_summary = models.TextField(max_length=10000)
    evidence_links = models.JSONField(default=list)
    criteria_snapshot = models.TextField(max_length=10000)
    checklist_snapshot = models.JSONField(default=list)
    target_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    actual_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=64, blank=True)
    submitted_at = models.DateTimeField(default=clock_now, editable=False)
    is_current = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task"],
                condition=Q(is_current=True),
                name="one_current_submission_per_task",
            )
        ]


class Review(models.Model):
    class Decision(models.TextChoices):
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.OneToOneField(Submission, on_delete=models.PROTECT, related_name="review")
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    feedback = models.TextField(max_length=10000, blank=True)
    reviewed_at = models.DateTimeField(default=clock_now, editable=False)


class ChangeProposal(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="change_proposals")
    proposer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    proposed_changes = models.JSONField(default=dict)
    reason = models.TextField(max_length=2000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    resolution_reason = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board = models.ForeignKey("boards.Board", on_delete=models.PROTECT, related_name="audit_events")
    board_revision = models.PositiveBigIntegerField()
    task = models.ForeignKey(
        Task, null=True, blank=True, on_delete=models.PROTECT, related_name="audit_events"
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=100)
    reason = models.TextField(max_length=2000, blank=True)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["board", "board_revision"]),
            models.Index(fields=["task", "created_at"]),
        ]
        ordering = ["board_revision", "created_at"]
