from __future__ import annotations

import pytest
from boards.models import Board, BoardColumn, BoardMembership
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()

pytestmark = pytest.mark.django_db(transaction=True)

TEST_PASSWORD = "Valid-Testing-Password-483!"  # noqa: S105

STANDARD_COLUMNS = [
    (BoardColumn.State.BACKLOG, "Backlog"),
    (BoardColumn.State.TODO, "To Do"),
    (BoardColumn.State.IN_PROGRESS, "In Progress"),
    (BoardColumn.State.BLOCKED, "Blocked"),
    (BoardColumn.State.REVIEW, "Review"),
    (BoardColumn.State.DONE, "Done"),
]


def create_board(admin, manager):
    board = Board.objects.create(name="Private board", created_by=admin)
    for position, (state, label) in enumerate(STANDARD_COLUMNS):
        BoardColumn.objects.create(
            board=board,
            state=state,
            name=label,
            position=position,
        )
    BoardMembership.objects.create(
        board=board,
        user=manager,
        role=BoardMembership.Role.MANAGER,
        created_by=admin,
    )
    return board


def test_anonymous_session_endpoint_returns_json_401():
    client = APIClient()
    response = client.get("/api/v1/session/me/")
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_non_member_board_snapshot_is_hidden_as_404():
    admin = User.objects.create_user(username="admin-api", password=None, is_staff=True)
    manager = User.objects.create_user(username="manager-api", password=None)
    outsider = User.objects.create_user(username="outsider-api", password=None)
    board = create_board(admin, manager)

    client = APIClient()
    client.force_authenticate(user=outsider)
    response = client.get(f"/api/v1/boards/{board.id}/snapshot")

    assert response.status_code == 404


def test_last_active_administrator_cannot_disable_itself():
    admin = User.objects.create_user(username="sole-admin", password=None, is_staff=True)
    client = APIClient()
    client.force_authenticate(user=admin)

    response = client.post(
        f"/api/v1/admin/users/{admin.id}/commands/disable",
        {"reason": "Test last-admin invariant"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="last-admin-disable",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "last_admin"
    admin.refresh_from_db()
    assert admin.is_active is True


def test_last_active_board_manager_cannot_be_removed():
    admin = User.objects.create_user(username="board-admin", password=None, is_staff=True)
    manager = User.objects.create_user(username="only-manager", password=None)
    board = create_board(admin, manager)

    client = APIClient()
    client.force_authenticate(user=admin)
    response = client.post(
        f"/api/v1/boards/{board.id}/memberships/{manager.id}/commands/remove",
        {"reason": "Test last-manager invariant"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="last-board-manager-remove",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "last_board_manager"
    membership = BoardMembership.objects.get(board=board, user=manager)
    assert membership.is_active is True


def test_csrf_login_and_session_generation_revocation():
    user = User.objects.create_user(
        username="session-user",
        password=TEST_PASSWORD,
        force_password_change=False,
    )
    client = APIClient(enforce_csrf_checks=True)

    csrf_response = client.get("/api/v1/session/csrf/")
    assert csrf_response.status_code == 200
    csrf_token = client.cookies["csrftoken"].value

    rejected = client.post(
        "/api/v1/session/login",
        {"username": user.username, "password": TEST_PASSWORD},
        format="json",
    )
    assert rejected.status_code == 403

    accepted = client.post(
        "/api/v1/session/login",
        {"username": user.username, "password": TEST_PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert accepted.status_code == 200
    assert accepted.json()["id"] == str(user.id)

    me = client.get("/api/v1/session/me/")
    assert me.status_code == 200

    user.session_generation += 1
    user.save(update_fields=["session_generation"])

    revoked = client.get("/api/v1/session/me/")
    assert revoked.status_code == 401
    assert revoked.json()["code"] == "session_revoked"


def test_login_lockout_after_five_failures():
    user = User.objects.create_user(
        username="locked-user",
        password=TEST_PASSWORD,
        force_password_change=False,
    )
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/v1/session/csrf/")
    csrf_token = client.cookies["csrftoken"].value

    for _ in range(5):
        response = client.post(
            "/api/v1/session/login",
            {"username": user.username, "password": "incorrect-value"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        assert response.status_code == 401

    locked = client.post(
        "/api/v1/session/login",
        {"username": user.username, "password": TEST_PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert locked.status_code == 429
    assert locked.json()["code"] == "login_throttled"


def test_admin_health_detail_reports_missing_backup_without_exposing_paths():
    admin = User.objects.create_user(username="health-admin", password=None, is_staff=True)
    client = APIClient()
    client.force_login(admin)

    response = client.get("/api/v1/health/detail")
    assert response.status_code == 200
    body = response.json()
    assert "disk" in body
    assert "queue" in body
    assert "heartbeats" in body
    assert body["backup"]["status"] == "not_configured"
    assert "backup_not_configured" in body["warnings"]
    assert "backup_target" not in body


def test_non_admin_cannot_read_detailed_health():
    member = User.objects.create_user(username="health-member", password=None)
    client = APIClient()
    client.force_login(member)

    response = client.get("/api/v1/health/detail")
    assert response.status_code == 403
