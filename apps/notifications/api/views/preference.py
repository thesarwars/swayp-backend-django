from drf_spectacular.utils import extend_schema

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)
from apps.notifications.api.serializers.preference import (
    NotificationPreferencesDataSerializer,
    NotificationPreferencesResponseSerializer,
    NotificationPreferenceUpdateSerializer,
)
from apps.notifications.services import NotificationPreferenceService


@extend_schema(tags=["Notifications"])
class NotificationPreferenceAPIView(BaseAPIView):
    """Read (GET) or upsert (PATCH) per-type channel preferences (E8-S3)."""

    service_class = NotificationPreferenceService

    @extend_schema(
        summary="List notification preferences",
        description=(
            "Every notification type with its effective channel switches, "
            "plus which channels the product can actually deliver on. Reads "
            "only: types the user has never touched come back at their "
            "defaults with isDefault=true and no row is created, so a later "
            "change to a default still reaches them."
        ),
        responses={
            200: NotificationPreferencesResponseSerializer,
            401: UNAUTHORIZED_RESPONSE,
        },
    )
    def get(self, request):
        return ApiResponse.success(
            data=NotificationPreferencesDataSerializer(
                self.service.get(user=request.user)
            ).data,
            message="Notification preferences retrieved.",
        )

    @extend_schema(
        summary="Update notification preferences",
        description=(
            "Upserts one row per named type; unnamed types and unnamed "
            "channels are untouched. Unknown types are rejected. SMS and "
            "push cannot be switched on — there is no delivery adapter this "
            "release (BRD §1.2) — and an item that names only sms/push is "
            "rejected too, because it could not change anything yet would "
            "still pin that type's remaining channels to today's defaults."
        ),
        request=NotificationPreferenceUpdateSerializer,
        responses={
            200: NotificationPreferencesResponseSerializer,
            400: BAD_REQUEST_RESPONSE,
            401: UNAUTHORIZED_RESPONSE,
        },
    )
    def patch(self, request):
        payload = NotificationPreferenceUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        return ApiResponse.success(
            data=NotificationPreferencesDataSerializer(
                self.service.update(
                    user=request.user,
                    updates=payload.validated_data["preferences"],
                )
            ).data,
            message="Notification preferences updated.",
        )
