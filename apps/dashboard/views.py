from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse

from .schemas import (
    profile_summary_schema,
)
from .serializers import (
    ProfileSummarySerializer,
)
from .services import DashboardService
import traceback


class ProfileSummaryAPIView(BaseAPIView):

    service_class = DashboardService

    @profile_summary_schema
    def get(self, request):
        try:
            print("========== Profile Summary Started ==========")

            result = self.service.get_profile_summary(
                user=request.user,
            )
            print("✓ Service completed")
            print(result)

            serializer = ProfileSummarySerializer(result)
            print("✓ Serializer completed")
            print(serializer.data)

            response = ApiResponse.success(
                data=serializer.data,
            )
            print("✓ Response generated")

            return response

        except Exception:
            print("\n========== EXCEPTION ==========")
            traceback.print_exc()
            print("================================\n")
            raise
    # def get(self, request):
    #     result = self.service.get_profile_summary(
    #         user=request.user,
    #     )

    #     serializer = ProfileSummarySerializer(
    #         result,
    #     )

    #     return ApiResponse.success(
    #         data=serializer.data,
    #     )