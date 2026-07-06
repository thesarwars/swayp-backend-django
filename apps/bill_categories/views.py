from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse

from .schemas import bill_category_list_schema
from .serializers import BillCategorySerializer
from .services import BillCategoryService


class BillCategoryListAPIView(BaseAPIView):

    service_class = BillCategoryService

    @bill_category_list_schema
    def get(self, request):
        categories = self.service.get_dashboard_categories()

        serializer = BillCategorySerializer(
            categories,
            many=True,
        )

        return ApiResponse.success(
            data=serializer.data
        )