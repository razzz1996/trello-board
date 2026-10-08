from __future__ import annotations

# ruff: noqa: E402, I001

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "productivity.settings")

import django

django.setup()

from accounts.models import AccountAuditEvent, User
from accounts.throttle import clear_success
from boards.deletion import delete_board
from boards.models import Board, BoardColumn, BoardLabel, BoardMembership
from core.models import RequestReceipt
from django.contrib.sessions.models import Session
from notifications.models import Job, Notification
from reports.models import ReportSnapshot
from workitems.models import AuditEvent

MODE = sys.argv[1]
ADMIN = os.environ["E2E_ADMIN_USERNAME"]
MEMBER = os.environ["E2E_MEMBER_USERNAME"]
MEMBER2 = os.environ["E2E_MEMBER2_USERNAME"]
PASSWORD = os.environ["E2E_PASSWORD"]
BOARD_NAME = os.environ["E2E_BOARD_NAME"]
def cleanup_users() -> None:
    users = list(User.objects.filter(username__startswith="e2e-"))
    if not users:
        return

    user_ids = {str(user.id) for user in users}
    User.objects.filter(id__in=[user.id for user in users]).update(is_active=False)

    for session in Session.objects.all():
        if str(session.get_decoded().get("_auth_user_id", "")) in user_ids:
            session.delete()

    for user in users:
        AuditEvent.objects.filter(actor=user).delete()
        AccountAuditEvent.objects.filter(actor=user).delete()
        AccountAuditEvent.objects.filter(target=user).delete()
        RequestReceipt.objects.filter(actor=user).delete()
        Job.objects.filter(payload__recipient_id=str(user.id)).delete()
        Notification.objects.filter(recipient=user).delete()
        ReportSnapshot.objects.filter(recipient=user).delete()
        BoardMembership.objects.filter(user=user).delete()
        clear_success(user.username, "")

    User.objects.filter(id__in=[user.id for user in users]).delete()


def cleanup_board() -> None:
    board = Board.objects.filter(name=BOARD_NAME).first()
    admin = User.objects.filter(username=ADMIN).first()
    if board is not None and admin is not None:
        delete_board(actor=admin, board_id=board.id, confirm_name=board.name)


if MODE == "cleanup":
    cleanup_board()
    cleanup_users()
    raise SystemExit(0)
if MODE != "setup":
    raise RuntimeError(f"Unknown mode: {MODE}")

cleanup_board()
cleanup_users()

admin = User.objects.create_user(
    username=ADMIN,
    password=PASSWORD,
    force_password_change=False,
    is_staff=True,
    is_active=True,
)
member = User.objects.create_user(
    username=MEMBER,
    password=PASSWORD,
    force_password_change=False,
    is_active=True,
)
member2 = User.objects.create_user(
    username=MEMBER2,
    password=PASSWORD,
    force_password_change=False,
    is_active=True,
)

board = Board.objects.create(name=BOARD_NAME, created_by=admin)
columns = [
    (BoardColumn.State.BACKLOG, "Inbox"),
    (BoardColumn.State.TODO, "To Do"),
    (BoardColumn.State.IN_PROGRESS, "In Progress"),
    (BoardColumn.State.BLOCKED, "Later"),
    (BoardColumn.State.DONE, "Done"),
]
for position, (state, name) in enumerate(columns):
    BoardColumn.objects.create(
        board=board,
        state=state,
        name=name,
        position=position,
    )

for position, color in enumerate(("green", "yellow", "orange", "red", "purple", "blue")):
    BoardLabel.objects.create(board=board, color=color, position=position)

for user, role in (
    (admin, BoardMembership.Role.MANAGER),
    (member, BoardMembership.Role.MEMBER),
    (member2, BoardMembership.Role.MEMBER),
):
    BoardMembership.objects.update_or_create(
        board=board,
        user=user,
        defaults={
            "role": role,
            "is_active": True,
            "created_by": admin,
        },
    )

print(str(board.id))
