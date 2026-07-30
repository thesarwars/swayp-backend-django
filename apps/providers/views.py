from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse

from .schemas import provider_list_schema

from .serializers import (
    ProviderSerializer,
    ProviderQuerySerializer,
)

from .services import ProviderService


class ProviderListAPIView(BaseAPIView):

    service_class = ProviderService

    @provider_list_schema
    def get(self, request):
        query = ProviderQuerySerializer(
            data=request.query_params
        )

        query.is_valid(raise_exception=True)

        result = self.service.list_providers(
            category_id=query.validated_data.get("categoryId"),
            search=query.validated_data.get("search"),
            page=query.validated_data["page"],
            page_size=query.validated_data["pageSize"],
        )

        serializer = ProviderSerializer(
            result["items"],
            many=True,
        )

        return ApiResponse.success(
            data=serializer.data,
            pagination=result["pagination"],
        )
