from drf_spectacular.utils import extend_schema

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


@extend_schema(
    tags=["Dashboard"],
    summary="Profile Summary",
    description=(
        "Returns the authenticated user's profile summary "
        "for the dashboard."
    ),
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
        )

        serializer = ProfileSummarySerializer(
            result,
        )

        return ApiResponse.success(
            data=serializer.data,
        )
