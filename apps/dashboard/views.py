from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse

from .schemas import (
    profile_summary_schema,
)
from .serializers import (
    ProfileSummarySerializer,
)
from .services import DashboardService


class ProfileSummaryAPIView(BaseAPIView):

    service_class = DashboardService

    @profile_summary_schema
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