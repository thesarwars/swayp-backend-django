from drf_spectacular.utils import extend_schema

from apps.ai_advisor.api.serializers.projection import (
    BalanceProjectionQuerySerializer,
    BalanceProjectionSerializer,
)
from apps.ai_advisor.services.projection_service import ProjectionService
from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse


@extend_schema(
    tags=["Flo (AI advisor)"],
    summary="Projected balance on a future date",
    description=(
        "Deterministic, no LLM: current balance, minus everything still owed "
        "on or before the date, minus money already committed out of this "
        "account. Bills come from each recurrence rule rather than only from "
        "materialised rows, so the answer stays exact past the point where "
        "occurrences have been pre-created."
    ),
    parameters=[BalanceProjectionQuerySerializer],
    responses=BalanceProjectionSerializer,
)
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

        return ApiResponse.success(
            data=BalanceProjectionSerializer(result).data,
            message="Projection computed.",
        )
