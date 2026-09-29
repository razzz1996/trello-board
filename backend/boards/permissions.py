from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import Board, BoardMembership


def visible_boards(user):
    if not user.is_authenticated or not user.is_active:
        return Board.objects.none()
    return Board.objects.filter(
        memberships__user=user,
        memberships__is_active=True,
    ).distinct()


def membership_for(user, board_id, *, for_update: bool = False) -> BoardMembership:
    if not user.is_authenticated or not user.is_active:
        raise Http404
    qs = BoardMembership.objects.select_related("board", "user").filter(
        board_id=board_id,
        user=user,
        is_active=True,
    )
    if for_update:
        qs = qs.select_for_update()
    membership = qs.first()
    if membership is None:
        raise Http404
    return membership


def require_board_member(user, board_id, *, for_update: bool = False) -> BoardMembership:
    return membership_for(user, board_id, for_update=for_update)


def require_board_manager(user, board_id, *, for_update: bool = False) -> BoardMembership:
    membership = membership_for(user, board_id, for_update=for_update)
    if membership.role != BoardMembership.Role.MANAGER:
        raise PermissionDenied("Board manager role required")
    return membership


def require_site_admin(user) -> None:
    if not user.is_authenticated or not user.is_active or not (user.is_staff or user.is_superuser):
        raise PermissionDenied("Administrator role required")
