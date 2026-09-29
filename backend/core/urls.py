from accounts.api import PasswordChangeView, SessionLoginView, SessionLogoutView
from boards.api import BoardListCreateView, BoardSnapshotView
from django.urls import path
from workitems.api import TaskCollectionView, TaskCommandView

from .views import csrf_bootstrap, current_user, liveness

urlpatterns = [
    path("health/live", liveness, name="health-live"),
    path("session/csrf/", csrf_bootstrap, name="session-csrf"),
    path("session/login", SessionLoginView.as_view(), name="session-login"),
    path("session/logout", SessionLogoutView.as_view(), name="session-logout"),
    path("session/password-change", PasswordChangeView.as_view(), name="session-password-change"),
    path("session/me/", current_user, name="session-me"),
    path("boards", BoardListCreateView.as_view(), name="boards"),
    path(
        "boards/<uuid:board_id>/snapshot",
        BoardSnapshotView.as_view(),
        name="board-snapshot",
    ),
    path("tasks", TaskCollectionView.as_view(), name="tasks"),
    path(
        "tasks/<uuid:task_id>/commands/<str:command>",
        TaskCommandView.as_view(),
        name="task-command",
    ),
]
