"""Device registration for push (E8-S5).

Called on every app launch, not only at sign-in: FCM rotates tokens, and a
client that only registered once would go quiet without any error to notice.
Registration is idempotent, so repeating it is the intended usage.
"""

from drf_spectacular.utils import extend_schema

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)
from apps.notifications.api.serializers.device import (
    DeviceRegisterSerializer,
    DeviceSerializer,
    DeviceUnregisterSerializer,
)
from apps.notifications.services.device_service import DeviceService


@extend_schema(tags=["Notifications"])
class DeviceRegisterAPIView(BaseAPIView):

    service_class = DeviceService

    @extend_schema(
        summary="Register this device for push notifications",
        description=(
            "Idempotent — call it on every launch, since FCM rotates tokens. "
            "A token already registered to another account is moved to the "
            "caller, which is what makes signing in on a shared device stop "
            "the previous user's notifications from arriving on it. The "
            "token is never echoed back."
        ),
        request=DeviceRegisterSerializer,
        responses={
            200: DeviceSerializer,
            400: BAD_REQUEST_RESPONSE,
            401: UNAUTHORIZED_RESPONSE,
        },
    )
    def post(self, request):
        payload = DeviceRegisterSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        device = self.service.register(
            user=request.user, **payload.validated_data
        )

        return ApiResponse.success(
            data=DeviceSerializer(device).data,
            message="Device registered for push notifications.",
        )


@extend_schema(tags=["Notifications"])
class DeviceUnregisterAPIView(BaseAPIView):

    service_class = DeviceService
    nullable_data = ("POST",)

    @extend_schema(
        summary="Stop push notifications to this device",
        description=(
            "Call on sign-out, so the next person to use the device does not "
            "receive the previous user's notifications. Idempotent, and "
            "scoped to the caller's own devices: a token is a bearer string, "
            "and without that scoping one account could silence another's."
        ),
        request=DeviceUnregisterSerializer,
        responses={
            200: None,
            400: BAD_REQUEST_RESPONSE,
            401: UNAUTHORIZED_RESPONSE,
        },
    )
    def post(self, request):
        payload = DeviceUnregisterSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        self.service.unregister(
            user=request.user, token=payload.validated_data["token"]
        )

        # Always 200, never 404: whether that token existed is not something
        # an unregister call should be able to probe for.
        return ApiResponse.success(
            data=None, message="Device unregistered."
        )
