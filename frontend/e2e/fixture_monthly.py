from __future__ import annotations

# ruff: noqa: E402, I001

import os
import sys
from pathlib import Path

MONTHLY_ROOT = Path(os.environ.get("E2E_MONTHLY_ROOT", r"C:\Users\PC 19\Desktop\MONTHLY EVALUATION"))
sys.path.insert(0, str(MONTHLY_ROOT / "backend"))
os.chdir(MONTHLY_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "productivity.settings")
os.environ.setdefault("HR_EVALUATIONS_ENABLED", "1")

import django

django.setup()

from accounts.models import User
from boards.models import BoardMembership
from django.contrib.sessions.models import Session

MODE = sys.argv[1]
USERNAME = os.environ["E2E_MEMBER_USERNAME"]
PASSWORD = os.environ["E2E_PASSWORD"]


def cleanup() -> None:
    users = list(User.objects.filter(username__startswith="e2e-"))
    if not users:
        return

    user_ids = {str(user.id) for user in users}
    User.objects.filter(id__in=[user.id for user in users]).update(is_active=False)

    for session in Session.objects.all():
        if str(session.get_decoded().get("_auth_user_id", "")) in user_ids:
            session.delete()

    BoardMembership.objects.filter(user__in=users).delete()
    User.objects.filter(id__in=[user.id for user in users]).delete()
if MODE == "cleanup":
    cleanup()
    raise SystemExit(0)

if MODE != "setup":
    raise RuntimeError(f"Unknown mode: {MODE}")

cleanup()
User.objects.create_user(
    username=USERNAME,
    password=PASSWORD,
    force_password_change=False,
    is_active=True,
)
