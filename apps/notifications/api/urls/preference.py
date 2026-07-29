from django.urls import path

from apps.notifications.api.views.preference import (
    NotificationPreferenceAPIView,
)

urlpatterns = [
    path(
        "preferences/",
        NotificationPreferenceAPIView.as_view(),
        name="notification-preferences",
    ),
]
