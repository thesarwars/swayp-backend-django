from django.urls import path

from apps.authentication.api.views.sessions import (
    SessionDetailAPIView,
    SessionListAPIView,
    SessionRevokeAllAPIView,
)

urlpatterns = [
    path("/sessions", SessionListAPIView.as_view(), name="sessions"),
    path(
        "/sessions/revoke-all",
        SessionRevokeAllAPIView.as_view(),
        name="sessions-revoke-all",
    ),
    path(
        "/sessions/<uuid:session_id>",
        SessionDetailAPIView.as_view(),
        name="session-detail",
    ),
]
