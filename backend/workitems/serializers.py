from __future__ import annotations

from rest_framework import serializers

from .models import (
    ChangeProposal,
    ChecklistItem,
    Comment,
    CommentEditHistory,
    CommitmentRevision,
    Review,
    Submission,
    Task,
)


class ChecklistItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChecklistItem
        fields = ["id", "text", "required", "position", "checked", "updated_at"]
        read_only_fields = fields


class CommitmentSerializer(serializers.ModelSerializer):
    owner_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = CommitmentRevision
        fields = [
            "id",
            "revision",
            "owner_id",
            "due_at",
            "priority",
            "acceptance_criteria",
            "required_checklist_snapshot",
            "reason",
            "created_at",
        ]
        read_only_fields = fields


class ReviewSerializer(serializers.ModelSerializer):
    reviewer_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Review
        fields = ["id", "reviewer_id", "decision", "feedback", "reviewed_at"]
        read_only_fields = fields


class SubmissionSerializer(serializers.ModelSerializer):
    review = ReviewSerializer(read_only=True)
    accountable_owner_id = serializers.UUIDField(read_only=True)
    submitting_actor_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Submission
        fields = [
            "id",
            "commitment_id",
            "accountable_owner_id",
            "submitting_actor_id",
            "result_summary",
            "evidence_links",
            "target_value",
            "actual_value",
            "unit",
            "submitted_at",
            "is_current",
            "review",
        ]
        read_only_fields = fields


class CommentEditHistorySerializer(serializers.ModelSerializer):
    editor_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = CommentEditHistory
        fields = [
            "id",
            "editor_id",
            "previous_body",
            "replacement_body",
            "edited_at",
        ]
        read_only_fields = fields


class CommentSerializer(serializers.ModelSerializer):
    author_id = serializers.UUIDField(read_only=True)
    author_username = serializers.CharField(
        source="author.username",
        read_only=True,
    )
    history = CommentEditHistorySerializer(many=True, read_only=True)

    class Meta:
        model = Comment
        fields = [
            "id",
            "author_id",
            "author_username",
            "body",
            "created_at",
            "corrected_at",
            "history",
        ]
        read_only_fields = fields


class ChangeProposalSerializer(serializers.ModelSerializer):
    proposer_id = serializers.UUIDField(read_only=True)
    resolved_by_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = ChangeProposal
        fields = [
            "id",
            "proposer_id",
            "proposed_changes",
            "reason",
            "status",
            "resolved_by_id",
            "resolution_reason",
            "created_at",
            "resolved_at",
        ]
        read_only_fields = fields


class TaskSerializer(serializers.ModelSerializer):
    column_state = serializers.CharField(source="column.state", read_only=True)
    current_owner_id = serializers.UUIDField(read_only=True, allow_null=True)
    original_owner_id = serializers.UUIDField(read_only=True, allow_null=True)
    current_commitment = CommitmentSerializer(read_only=True)
    checklist_items = ChecklistItemSerializer(many=True, read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    change_proposals = ChangeProposalSerializer(many=True, read_only=True)
    submissions = SubmissionSerializer(many=True, read_only=True)

    class Meta:
        model = Task
        fields = [
            "id",
            "board_id",
            "column_id",
            "column_state",
            "title",
            "description",
            "priority",
            "current_owner_id",
            "original_owner_id",
            "row_version",
            "position",
            "draft_due_at",
            "draft_acceptance_criteria",
            "committed_at",
            "current_commitment",
            "is_cancelled",
            "cancelled_at",
            "cancelled_reason",
            "checklist_items",
            "comments",
            "change_proposals",
            "submissions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
