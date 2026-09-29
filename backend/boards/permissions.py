from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import Http404

from .models import Board, BoardMembership


def visible_boards(user):
    if not user.is_authenticated or not user.is_active:
        return Board.objects.none()
    return Board.objects.all()


def membership_for(user, board_id, *, for_update: bool = False) -> BoardMembership:
    if not user.is_authenticated or not user.is_active:
        raise Http404

    board = Board.objects.select_related("created_by").filter(pk=board_id).first()
    if board is None:
        raise Http404

    qs = BoardMembership.objects.select_related("board", "user").filter(
        board=board,
        user=user,
    )
    if for_update:
        qs = qs.select_for_update()
    membership = qs.first()
    desired_role = (
        BoardMembership.Role.MANAGER
        if user.is_staff or user.is_superuser
        else BoardMembership.Role.MEMBER
    )

    if membership is None:
        try:
            membership = BoardMembership.objects.create(
                board=board,
                user=user,
                role=desired_role,
                is_active=True,
                created_by=board.created_by,
            )
        except IntegrityError:
            membership = BoardMembership.objects.select_related("board", "user").get(
                board=board,
                user=user,
            )
    elif not membership.is_active or (
        desired_role == BoardMembership.Role.MANAGER
        and membership.role != BoardMembership.Role.MANAGER
    ):
        membership.is_active = True
        if desired_role == BoardMembership.Role.MANAGER:
            membership.role = BoardMembership.Role.MANAGER
        membership.save(update_fields=["is_active", "role"])

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
