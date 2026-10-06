from accounts.api import (
    AdminUserCollectionView,
    AdminUserCommandView,
    PasswordChangeView,
    SessionLoginView,
    SessionLogoutView,
)
from boards.api import (
    BoardColumnCollectionView,
    BoardColumnCommandView,
    BoardDeleteView,
    BoardListCreateView,
    BoardMembershipCollectionView,
    BoardMembershipCommandView,
    BoardSnapshotView,
)
from django.urls import path
from notifications.api import NotificationInboxView, NotificationReadView
from reports.api import ReportCollectionView, ReportDetailView
from schedules.api import ScheduleCollectionView, ScheduleCommandView, SchedulePreviewView
from workitems.api import TaskCollectionView, TaskCommandView, TaskDeleteView

from .views import csrf_bootstrap, current_user, health_detail, liveness, readiness

urlpatterns = [
    path("health/live", liveness, name="health-live"),
    path("health/ready", readiness, name="health-ready"),
    path("health/detail", health_detail, name="health-detail"),
    path("session/csrf/", csrf_bootstrap, name="session-csrf"),
    path("session/login", SessionLoginView.as_view(), name="session-login"),
    path("session/logout", SessionLogoutView.as_view(), name="session-logout"),
    path("session/password-change", PasswordChangeView.as_view(), name="session-password-change"),
    path("session/me/", current_user, name="session-me"),
    path("admin/users", AdminUserCollectionView.as_view(), name="admin-users"),
    path(
        "admin/users/<uuid:user_id>/commands/<str:command>",
        AdminUserCommandView.as_view(),
        name="admin-user-command",
    ),
    path("boards", BoardListCreateView.as_view(), name="boards"),
    path(
        "boards/<uuid:board_id>/snapshot",
        BoardSnapshotView.as_view(),
        name="board-snapshot",
    ),
    path(
        "boards/<uuid:board_id>/columns",
        BoardColumnCollectionView.as_view(),
        name="board-columns",
    ),
    path(
        "boards/<uuid:board_id>/columns/<uuid:column_id>/commands/<str:command>",
        BoardColumnCommandView.as_view(),
        name="board-column-command",
    ),
    path(
        "boards/<uuid:board_id>/delete",
        BoardDeleteView.as_view(),
        name="board-delete",
    ),
    path(
        "boards/<uuid:board_id>/memberships",
        BoardMembershipCollectionView.as_view(),
        name="board-memberships",
    ),
    path(
        "boards/<uuid:board_id>/memberships/<uuid:user_id>/commands/<str:command>",
        BoardMembershipCommandView.as_view(),
        name="board-membership-command",
    ),
    path("notifications", NotificationInboxView.as_view(), name="notifications"),
    path(
        "notifications/<uuid:notification_id>/read",
        NotificationReadView.as_view(),
        name="notification-read",
    ),
    path("reports", ReportCollectionView.as_view(), name="reports"),
    path("reports/<uuid:report_id>", ReportDetailView.as_view(), name="report-detail"),
    path("schedules", ScheduleCollectionView.as_view(), name="schedules"),
    path("schedules/preview", SchedulePreviewView.as_view(), name="schedule-preview"),
    path(
        "schedules/<uuid:schedule_id>/commands/<str:command>",
        ScheduleCommandView.as_view(),
        name="schedule-command",
    ),
    path("tasks", TaskCollectionView.as_view(), name="tasks"),
    path(
        "tasks/<uuid:task_id>/delete",
        TaskDeleteView.as_view(),
        name="task-delete",
    ),
    path(
        "tasks/<uuid:task_id>/commands/<str:command>",
        TaskCommandView.as_view(),
        name="task-command",
    ),
]
