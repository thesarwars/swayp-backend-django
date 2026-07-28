from rest_framework import status
from rest_framework.response import Response

from apps.ai_advisor.api.serializers.projection import (
    BalanceProjectionQuerySerializer,
    BalanceProjectionSerializer,
)
from apps.ai_advisor.services.projection_service import ProjectionService
from apps.common.base_views import BaseAPIView


class BalanceProjectionAPIView(BaseAPIView):
    """Deterministic balance projection for a future date (E7-S3)."""

    def get(self, request):
        query = BalanceProjectionQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        result = ProjectionService().project(
            user=request.user,
            account_id=query.validated_data["account"],
            target_date=query.validated_data["date"],
        )

        return Response(
            BalanceProjectionSerializer(result).data,
            status=status.HTTP_200_OK,
        )
