from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import Board, BoardMembership


def visible_boards(user):
    if not user.is_authenticated or not user.is_active:
        return Board.objects.none()
    return (
        Board.objects.filter(
            memberships__user=user,
            memberships__is_active=True,
            archived=False,
        )
        .distinct()
    )


def membership_for(user, board_id, *, for_update: bool = False) -> BoardMembership:
    if not user.is_authenticated or not user.is_active:
        raise Http404

    qs = BoardMembership.objects.select_related("board", "user").filter(
        board_id=board_id,
        user=user,
        is_active=True,
        board__archived=False,
    )
    if for_update:
        qs = qs.select_for_update()
    membership = qs.first()
    if membership is None:
        # Deliberately return 404 rather than 403 so a non-member cannot
        # discover that a private board exists by probing its URL.
        raise Http404

    return membership


def require_board_member(user, board_id, *, for_update: bool = False) -> BoardMembership:
    return membership_for(user, board_id, for_update=for_update)


def require_board_manager(user, board_id, *, for_update: bool = False) -> BoardMembership:
    membership = membership_for(user, board_id, for_update=for_update)
    if user.is_staff or user.is_superuser:
        return membership
    if membership.role != BoardMembership.Role.MANAGER:
        raise PermissionDenied("Board manager role required")
    return membership


def require_site_admin(user) -> None:
    if not user.is_authenticated or not user.is_active or not (user.is_staff or user.is_superuser):
        raise PermissionDenied("Administrator role required")


def require_board_manager_or_site_admin(user, board_id) -> BoardMembership | None:
    """Allow global administrators or managers of the specific board."""
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied("Active account required")
    if user.is_staff or user.is_superuser:
        return None
    return require_board_manager(user, board_id)
