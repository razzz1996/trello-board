from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


@receiver(user_logged_in)
def set_session_generation(sender, request, user, **kwargs) -> None:
    if request is not None:
        request.session["auth_generation"] = user.session_generation
        request.session["auth_started_at"] = timezone.now().timestamp()


@receiver(post_save, sender=get_user_model())
def add_new_user_to_existing_boards(sender, instance, created, **kwargs) -> None:
    if not created or not instance.is_active:
        return

    from boards.models import Board, BoardMembership

    role = (
        BoardMembership.Role.MANAGER
        if instance.is_staff or instance.is_superuser
        else BoardMembership.Role.MEMBER
    )
    memberships = [
        BoardMembership(
            board=board,
            user=instance,
            role=role,
            is_active=True,
            created_by=board.created_by,
        )
        for board in Board.objects.select_related("created_by").all()
    ]
    if memberships:
        BoardMembership.objects.bulk_create(memberships, ignore_conflicts=True)
