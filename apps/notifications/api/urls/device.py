from django.urls import path

from apps.notifications.api.views.device import (
    DeviceRegisterAPIView,
    DeviceUnregisterAPIView,
)

urlpatterns = [
    path(
        "/devices/register",
        DeviceRegisterAPIView.as_view(),
        name="notification-device-register",
    ),
    path(
        "/devices/unregister",
        DeviceUnregisterAPIView.as_view(),
        name="notification-device-unregister",
    ),
]
