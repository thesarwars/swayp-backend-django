from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)
from apps.dashboard.api.serializers.profile_summary import (
    ProfileSummaryResponseSerializer,
    ProfileSummarySerializer,
)
from apps.dashboard.services.dashboard_service import DashboardService



def _zone(name):
    if not name:
        return None

    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError({"tz": ["Unknown time zone. Use an IANA name."]})


@extend_schema(
    tags=["Dashboard"],
    summary="Profile Summary",
    description=(
        "The signed-in user's name, picture, greeting and unread count. "
        "Send `tz` (an IANA zone such as `Asia/Dhaka`) to pick the greeting "
        "by the user's own clock; without it US Eastern is used. An unknown "
        "zone is a 400."
    ),
    parameters=[
        OpenApiParameter(
            "tz", str, required=False,
            description="IANA time zone, e.g. America/Chicago.",
        )
    ],
    responses={
        200: ProfileSummaryResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)
class ProfileSummaryAPIView(BaseAPIView):

    service_class = DashboardService

    def get(self, request):
        result = self.service.get_profile_summary(
            user=request.user,
            tz=_zone(request.query_params.get("tz")),
            request=request,
        )

        serializer = ProfileSummarySerializer(
            result,
        )

        return ApiResponse.success(
            data=serializer.data,
        )
