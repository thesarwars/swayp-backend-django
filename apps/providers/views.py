from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.api_response import success_response

from .serializers import (
    ProviderSerializer,
    ProviderQuerySerializer,
    ProviderSearchQuerySerializer,
)
from .services import ProviderService
from .schemas import (
    provider_list_schema,
    provider_search_schema,
)


class ProviderListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    service = ProviderService()

    @provider_list_schema
    def get(self, request):
        query = ProviderQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        result = self.service.list_providers(
            category_id=query.validated_data.get("categoryId"),
            search=query.validated_data.get("search"),
            page=query.validated_data["page"],
            page_size=query.validated_data["pageSize"],
        )

        serializer = ProviderSerializer(
            instance=result["items"],
            many=True,
        )

        return success_response(
            data=serializer.data,
            pagination=result["pagination"],
        )


class ProviderSearchAPIView(APIView):
    permission_classes = [IsAuthenticated]

    service = ProviderService()

    @provider_search_schema
    def get(self, request):
        query = ProviderSearchQuerySerializer(
            data=request.query_params
        )

        query.is_valid(raise_exception=True)

        result = self.service.list_providers(
            search=query.validated_data["q"],
            page=query.validated_data["page"],
            page_size=query.validated_data["pageSize"],
        )

        serializer = ProviderSerializer(
            instance=result["items"],
            many=True,
        )   

        return success_response(
            data=serializer.data,
            pagination=result["pagination"],
        )