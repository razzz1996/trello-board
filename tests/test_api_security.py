from __future__ import annotations

import pytest
from accounts.models import AccountAuditEvent
from accounts.throttle import client_address
from boards.models import Board, BoardColumn, BoardMembership
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.utils import timezone
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


def test_every_active_user_can_open_any_board():
    admin = User.objects.create_user(username="admin-api", password=None, is_staff=True)
    manager = User.objects.create_user(username="manager-api", password=None)
    outsider = User.objects.create_user(username="outsider-api", password=None)
    board = create_board(admin, manager)

    client = APIClient()
    client.force_authenticate(user=outsider)
    response = client.get(f"/api/v1/boards/{board.id}/snapshot")

    assert response.status_code == 200
    assert response.json()["membership"]["role"] == BoardMembership.Role.MEMBER
    membership = BoardMembership.objects.get(board=board, user=outsider)
    assert membership.is_active is True


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
    csrf_token = client.cookies[settings.CSRF_COOKIE_NAME].value

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
    assert revoked.json()["code"] in {"authentication_required", "session_revoked"}


def test_login_lockout_after_five_failures():
    user = User.objects.create_user(
        username="locked-user",
        password=TEST_PASSWORD,
        force_password_change=False,
    )
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/v1/session/csrf/")
    csrf_token = client.cookies[settings.CSRF_COOKIE_NAME].value

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
    csrf_token = client.cookies[settings.CSRF_COOKIE_NAME].value
    login_response = client.post(
        "/api/v1/session/login",
        {"username": user.username, "password": TEST_PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert login_response.status_code == 200
    assert login_response.json()["force_password_change"] is True

    csrf_token = client.cookies[settings.CSRF_COOKIE_NAME].value
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


def test_regular_user_cannot_create_board():
    user = User.objects.create_user(username="board-creator", password=None)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/v1/boards",
        {"name": "Forbidden Board", "manager_user_ids": []},
        format="json",
        HTTP_IDEMPOTENCY_KEY="member-board-create",
    )

    assert response.status_code == 403
    assert not Board.objects.filter(name="Forbidden Board").exists()


def test_admin_created_board_is_immediately_visible_and_editable_to_all_users():
    admin = User.objects.create_user(username="global-board-admin", password=None, is_staff=True)
    member_a = User.objects.create_user(username="global-member-a", password=None)
    member_b = User.objects.create_user(username="global-member-b", password=None)

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    created = admin_client.post(
        "/api/v1/boards",
        {"name": "Global Operations", "manager_user_ids": []},
        format="json",
        HTTP_IDEMPOTENCY_KEY="admin-global-board-create",
    )
    assert created.status_code == 201
    board = Board.objects.get(pk=created.json()["id"])

    assert BoardMembership.objects.get(board=board, user=admin).role == BoardMembership.Role.MANAGER
    assert BoardMembership.objects.get(board=board, user=member_a).role == BoardMembership.Role.MEMBER
    assert BoardMembership.objects.get(board=board, user=member_b).role == BoardMembership.Role.MEMBER

    member_client = APIClient()
    member_client.force_authenticate(user=member_a)
    boards = member_client.get("/api/v1/boards")
    assert boards.status_code == 200
    assert str(board.id) in {row["id"] for row in boards.json()}

    snapshot = member_client.get(f"/api/v1/boards/{board.id}/snapshot")
    assert snapshot.status_code == 200
    assert [column["name"] for column in snapshot.json()["columns"]] == [
        "Inbox",
        "To Do",
        "In Progress",
        "Later",
        "Done",
    ]

    card = member_client.post(
        "/api/v1/tasks",
        {
            "board_id": str(board.id),
            "title": "Member-created card",
            "priority": 1,
            "owner_id": str(member_b.id),
            "draft_due_at": None,
            "draft_acceptance_criteria": "",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="global-member-card-create",
    )
    assert card.status_code == 201
    assert card.json()["current_owner_id"] == str(member_b.id)


def test_board_manager_can_share_board_by_username():
    creator = User.objects.create_user(username="share-manager", password=None)
    teammate = User.objects.create_user(username="share-teammate", password=None)
    board = create_board(creator, creator)

    client = APIClient()
    client.force_authenticate(user=creator)
    added = client.post(
        f"/api/v1/boards/{board.id}/memberships",
        {
            "username": teammate.username,
            "role": "MEMBER",
            "reason": "Share regression test",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="manager-share-board",
    )
    assert added.status_code == 201
    assert added.json()["username"] == teammate.username

    listing = client.get(f"/api/v1/boards/{board.id}/memberships")
    assert listing.status_code == 200
    assert {row["username"] for row in listing.json()} >= {
        creator.username,
        teammate.username,
    }

    promoted = client.post(
        f"/api/v1/boards/{board.id}/memberships/{teammate.id}/commands/set_role",
        {"role": "MANAGER", "reason": "Promote collaborator"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="manager-promote-board-user",
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "MANAGER"


def test_new_user_is_automatically_added_to_existing_boards():
    admin = User.objects.create_user(username="membership-sync-admin", password=None, is_staff=True)
    board = create_board(admin, admin)

    member = User.objects.create_user(username="membership-sync-member", password=None)

    membership = BoardMembership.objects.get(board=board, user=member)
    assert membership.is_active is True
    assert membership.role == BoardMembership.Role.MEMBER


def test_five_failures_do_not_lock_other_account_on_shared_office_address():
    first = User.objects.create_user(
        username="shared-address-first",
        password=TEST_PASSWORD,
        force_password_change=False,
    )
    second = User.objects.create_user(
        username="shared-address-second",
        password=TEST_PASSWORD,
        force_password_change=False,
    )
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/v1/session/csrf/")
    csrf_token = client.cookies[settings.CSRF_COOKIE_NAME].value

    for _ in range(5):
        response = client.post(
            "/api/v1/session/login",
            {"username": first.username, "password": "incorrect-value"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        assert response.status_code == 401

    allowed = client.post(
        "/api/v1/session/login",
        {"username": second.username, "password": TEST_PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert allowed.status_code == 200
    assert allowed.json()["username"] == second.username


def test_client_address_normalizes_vite_forwarded_ipv4_and_rejects_spoofing():
    factory = RequestFactory()
    proxied = factory.get(
        "/",
        REMOTE_ADDR="127.0.0.1",
        HTTP_X_FORWARDED_FOR="203.0.113.10, ::ffff:172.16.0.222",
    )
    assert client_address(proxied) == "172.16.0.222"

    direct = factory.get(
        "/",
        REMOTE_ADDR="172.16.0.55",
        HTTP_X_FORWARDED_FOR="203.0.113.10",
    )
    assert client_address(direct) == "172.16.0.55"


def test_sessions_are_persistent_bounded_and_cookie_isolated():
    assert settings.SESSION_COOKIE_NAME == "emega_productivity_sessionid"
    assert settings.CSRF_COOKIE_NAME == "emega_productivity_csrftoken"
    assert settings.SESSION_COOKIE_NAME != "monthly_evaluation_sessionid"
    assert settings.CSRF_COOKIE_NAME != "monthly_evaluation_csrftoken"
    assert settings.SESSION_COOKIE_AGE == 30 * 24 * 60 * 60
    assert settings.PRODUCTIVITY_SESSION_ABSOLUTE_AGE == 90 * 24 * 60 * 60
    assert settings.SESSION_SAVE_EVERY_REQUEST is True
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is False
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.SESSION_COOKIE_PATH == "/"
    assert settings.CSRF_COOKIE_PATH == "/"


def test_absolute_session_lifetime_is_enforced():
    user = User.objects.create_user(
        username="absolute-session-user",
        password=TEST_PASSWORD,
        force_password_change=False,
    )
    client = APIClient()
    client.force_login(user)
    session = client.session
    session["auth_generation"] = user.session_generation
    session["auth_started_at"] = (
        timezone.now().timestamp() - settings.PRODUCTIVITY_SESSION_ABSOLUTE_AGE - 1
    )
    session.save()

    expired = client.get("/api/v1/session/me/")

    assert expired.status_code == 401
    assert expired.json()["code"] == "session_expired"


def test_explicit_logout_invalidates_backend_session():
    user = User.objects.create_user(
        username="logout-user",
        password=TEST_PASSWORD,
        force_password_change=False,
    )
    client = APIClient()
    client.force_login(user)

    assert client.get("/api/v1/session/me/").status_code == 200
    assert client.post("/api/v1/session/logout").status_code == 204
    assert client.get("/api/v1/session/me/").status_code == 401


def test_login_rotates_preexisting_session_identifier():
    user = User.objects.create_user(
        username="rotation-user",
        password=TEST_PASSWORD,
        force_password_change=False,
    )
    client = APIClient(enforce_csrf_checks=True)
    session = client.session
    session["prelogin"] = "value"
    session.save()
    old_session_key = session.session_key

    client.get("/api/v1/session/csrf/")
    csrf_token = client.cookies[settings.CSRF_COOKIE_NAME].value
    response = client.post(
        "/api/v1/session/login",
        {"username": user.username, "password": TEST_PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert response.status_code == 200
    assert client.session.session_key != old_session_key
    assert "auth_started_at" in client.session


def test_admin_disable_revokes_existing_user_session():
    admin = User.objects.create_user(username="revoke-admin", password=None, is_staff=True)
    user = User.objects.create_user(
        username="revoke-member",
        password=TEST_PASSWORD,
        force_password_change=False,
    )

    user_client = APIClient()
    user_client.force_login(user)
    user_session = user_client.session
    user_session["auth_generation"] = user.session_generation
    user_session["auth_started_at"] = timezone.now().timestamp()
    user_session.save()
    assert user_client.get("/api/v1/session/me/").status_code == 200

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    disabled = admin_client.post(
        f"/api/v1/admin/users/{user.id}/commands/disable",
        {"reason": "Session revocation test"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="disable-session-revocation",
    )
    assert disabled.status_code == 200

    revoked = user_client.get("/api/v1/session/me/")
    assert revoked.status_code == 401
    assert revoked.json()["code"] in {"authentication_required", "session_revoked"}

def test_password_change_preserves_current_session_and_revokes_other_sessions():
    user = User.objects.create_user(
        username="password-change-revoke",
        password=TEST_PASSWORD,
        force_password_change=False,
    )
    primary = APIClient()
    secondary = APIClient()
    for client in (primary, secondary):
        client.force_login(user)
        session = client.session
        session["auth_generation"] = user.session_generation
        session["auth_started_at"] = timezone.now().timestamp()
        session.save()

    changed = primary.post(
        "/api/v1/session/password-change",
        {
            "current_password": TEST_PASSWORD,
            "new_password": TEST_PASSWORD + "Changed!",
        },
        format="json",
    )
    assert changed.status_code == 200
    assert primary.get("/api/v1/session/me/").status_code == 200

    revoked = secondary.get("/api/v1/session/me/")
    assert revoked.status_code == 401


def test_admin_password_reset_revokes_existing_session():
    admin = User.objects.create_user(username="reset-revoke-admin", password=None, is_staff=True)
    user = User.objects.create_user(
        username="reset-revoke-member",
        password=TEST_PASSWORD,
        force_password_change=False,
    )
    user_client = APIClient()
    user_client.force_login(user)
    session = user_client.session
    session["auth_generation"] = user.session_generation
    session["auth_started_at"] = timezone.now().timestamp()
    session.save()
    assert user_client.get("/api/v1/session/me/").status_code == 200

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    reset = admin_client.post(
        f"/api/v1/admin/users/{user.id}/commands/reset_password",
        {
            "temporary_password": TEST_PASSWORD + "Reset!",
            "reason": "Revoke active sessions",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="reset-session-revocation",
    )
    assert reset.status_code == 200
    assert user_client.get("/api/v1/session/me/").status_code == 401
