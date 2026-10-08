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
    BoardRenameView,
    BoardSnapshotView,
)
from boards.menu_api import (
    ArchivedListCommandView,
    ArchivedTaskCommandView,
    BoardActivityView,
    BoardArchiveView,
    BoardBackgroundImageView,
    BoardBackgroundView,
    BoardLabelCollectionView,
    BoardLabelCommandView,
    BoardPresenceView,
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
        "boards/<uuid:board_id>/rename",
        BoardRenameView.as_view(),
        name="board-rename",
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
    path(
        "boards/<uuid:board_id>/presence",
        BoardPresenceView.as_view(),
        name="board-presence",
    ),
    path(
        "boards/<uuid:board_id>/background",
        BoardBackgroundView.as_view(),
        name="board-background",
    ),
    path(
        "boards/<uuid:board_id>/background-image",
        BoardBackgroundImageView.as_view(),
        name="board-background-image",
    ),
    path(
        "boards/<uuid:board_id>/labels",
        BoardLabelCollectionView.as_view(),
        name="board-labels",
    ),
    path(
        "boards/<uuid:board_id>/labels/<uuid:label_id>/commands/<str:command>",
        BoardLabelCommandView.as_view(),
        name="board-label-command",
    ),
    path(
        "boards/<uuid:board_id>/activity",
        BoardActivityView.as_view(),
        name="board-activity",
    ),
    path(
        "boards/<uuid:board_id>/archived",
        BoardArchiveView.as_view(),
        name="board-archived",
    ),
    path(
        "boards/<uuid:board_id>/archived/tasks/<uuid:task_id>/commands/<str:command>",
        ArchivedTaskCommandView.as_view(),
        name="board-archived-task-command",
    ),
    path(
        "boards/<uuid:board_id>/archived/lists/<uuid:column_id>/commands/<str:command>",
        ArchivedListCommandView.as_view(),
        name="board-archived-list-command",
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
