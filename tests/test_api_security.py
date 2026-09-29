from __future__ import annotations

import pytest
from accounts.models import AccountAuditEvent
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


def test_task_create_receipt_serializes_uuid_fields_and_replays_cleanly():
    admin = User.objects.create_user(username="admin-create", password=None, is_staff=True)
    manager = User.objects.create_user(username="manager-create", password=None)
    board = create_board(admin, manager)

    client = APIClient()
    client.force_authenticate(user=manager)
    payload = {
        "board_id": str(board.id),
        "title": "CSR AUTO REPLY",
        "priority": 3,
        "owner_id": str(manager.id),
        "draft_due_at": "2026-09-30T10:00:00+08:00",
        "draft_acceptance_criteria": "",
    }

    first = client.post(
        "/api/v1/tasks",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="create-task-uuid-response",
    )
    second = client.post(
        "/api/v1/tasks",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="create-task-uuid-response",
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert first.json()["board_id"] == str(board.id)
    assert isinstance(first.json()["column_id"], str)
    assert board.tasks.filter(title="CSR AUTO REPLY").count() == 1


def test_successful_admin_state_change_is_audited():
    admin = User.objects.create_user(username="state-admin", password=None, is_staff=True)
    target = User.objects.create_user(username="state-target", password=None)
    client = APIClient()
    client.force_authenticate(user=admin)

    disabled = client.post(
        f"/api/v1/admin/users/{target.id}/commands/disable",
        {"reason": "Regression test successful disable"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="successful-disable-audit",
    )

    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    target.refresh_from_db()
    assert target.is_active is False
    event = AccountAuditEvent.objects.get(target=target, action="disable")
    assert event.actor_id == admin.id
    assert event.before["is_active"] is True
    assert event.after["is_active"] is False

    enabled = client.post(
        f"/api/v1/admin/users/{target.id}/commands/enable",
        {"reason": "Regression test successful enable"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="successful-enable-audit",
    )

    assert enabled.status_code == 200
    assert enabled.json()["is_active"] is True
    assert AccountAuditEvent.objects.filter(target=target, action="enable").exists()


def test_admin_create_and_reset_password_are_audited_without_exposing_password():
    admin = User.objects.create_user(username="create-admin", password=None, is_staff=True)
    client = APIClient()
    client.force_authenticate(user=admin)

    payload = {
        "username": "created-via-admin",
        "temporary_password": TEST_PASSWORD,
        "is_admin": False,
        "reason": "Regression test account creation",
    }
    created = client.post(
        "/api/v1/admin/users",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="admin-create-audited",
    )
    replay = client.post(
        "/api/v1/admin/users",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="admin-create-audited",
    )

    assert created.status_code == 201
    assert replay.status_code == 201
    assert created.json() == replay.json()
    assert "password" not in created.json()
    target = User.objects.get(username="created-via-admin")
    assert target.force_password_change is True
    assert target.check_password(TEST_PASSWORD)
    assert AccountAuditEvent.objects.filter(
        actor=admin,
        target=target,
        action="create_user",
    ).exists()

    replacement = TEST_PASSWORD + "Reset!"
    reset = client.post(
        f"/api/v1/admin/users/{target.id}/commands/reset_password",
        {
            "temporary_password": replacement,
            "reason": "Regression test password reset",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="admin-reset-audited",
    )

    assert reset.status_code == 200
    assert "password" not in reset.json()
    target.refresh_from_db()
    assert target.force_password_change is True
    assert target.check_password(replacement)
    assert AccountAuditEvent.objects.filter(
        actor=admin,
        target=target,
        action="reset_password",
    ).exists()


def test_forced_password_change_succeeds_and_keeps_session_valid():
    user = User.objects.create_user(
        username="forced-password-user",
        password=TEST_PASSWORD,
        force_password_change=True,
    )
    client = APIClient(enforce_csrf_checks=True)

    client.get("/api/v1/session/csrf/")
    csrf_token = client.cookies["csrftoken"].value
    login_response = client.post(
        "/api/v1/session/login",
        {"username": user.username, "password": TEST_PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert login_response.status_code == 200
    assert login_response.json()["force_password_change"] is True

    csrf_token = client.cookies["csrftoken"].value
    replacement = TEST_PASSWORD + "Permanent!"
    changed = client.post(
        "/api/v1/session/password-change",
        {
            "current_password": TEST_PASSWORD,
            "new_password": replacement,
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert changed.status_code == 200
    assert changed.json()["force_password_change"] is False
    user.refresh_from_db()
    assert user.force_password_change is False
    assert user.check_password(replacement)

    me = client.get("/api/v1/session/me/")
    assert me.status_code == 200
    assert me.json()["username"] == user.username
    assert me.json()["force_password_change"] is False
