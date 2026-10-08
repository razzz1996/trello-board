from __future__ import annotations

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils import timezone


@receiver(user_logged_in)
def set_session_generation(sender, request, user, **kwargs) -> None:
    if request is not None:
        request.session["auth_generation"] = user.session_generation
        request.session["auth_started_at"] = timezone.now().timestamp()
