from django.urls import path

from apps.authentication.api.views.token import (
    LogoutView,
    RefreshView,
)

urlpatterns = [
    path(
        "refresh/",
        RefreshView.as_view(),
        name="refresh",
    ),

    path(
        "logout/",
        LogoutView.as_view(),
        name="logout",
    ),
]
