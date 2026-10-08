from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Board(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    revision = models.PositiveBigIntegerField(default=1)
    archived = models.BooleanField(default=False)
    background_key = models.CharField(max_length=32, blank=True, default="rainbow")
    background_image = models.FileField(upload_to="board_backgrounds/", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_boards"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]


class BoardLabel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="labels")
    color = models.CharField(max_length=16)
    name = models.CharField(max_length=100, blank=True, default="")
    description = models.CharField(max_length=500, blank=True, default="")
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "created_at"]
        indexes = [models.Index(fields=["board", "position"])]


class BoardColumn(models.Model):
    class State(models.TextChoices):
        BACKLOG = "BACKLOG", "Inbox"
        TODO = "TODO", "To Do"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        BLOCKED = "BLOCKED", "Later"
        REVIEW = "REVIEW", "Review (legacy)"
        DONE = "DONE", "Done"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="columns")
    state = models.CharField(max_length=64)
    name = models.CharField(max_length=100)
    position = models.PositiveSmallIntegerField()
    is_custom = models.BooleanField(default=False)
    color = models.CharField(max_length=16, blank=True, default="")
    text_color = models.CharField(max_length=16, blank=True, default="")
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["board", "state"], name="uq_board_column_state"),
            models.UniqueConstraint(fields=["board", "position"], name="uq_board_column_position"),
        ]
        ordering = ["position"]


class BoardPresence(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="presences")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="board_presences"
    )
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["board", "user"], name="uq_board_presence_user")
        ]
        indexes = [models.Index(fields=["board", "last_seen_at"])]


class BoardMembership(models.Model):
    class Role(models.TextChoices):
        MEMBER = "MEMBER", "Member"
        MANAGER = "MANAGER", "Manager"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="board_memberships"
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["board", "user"], name="uq_board_user")]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["board", "role", "is_active"]),
        ]
