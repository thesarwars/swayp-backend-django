from drf_spectacular.utils import extend_schema

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)
from apps.dashboard.api.serializers.home import (
    HomeQuerySerializer,
    HomeResponseSerializer,
    HomeSerializer,
)
from apps.dashboard.services.home_service import HomeService


@extend_schema(
    tags=["Dashboard"],
    summary="Home dashboard",
    description=(
        "Greeting, stat cards, recent bills, vendors preview and the "
        "right-rail pay panel in one round-trip. `pay_panel.tabs` counts "
        "occurrences while `stats.total_bills` counts bills, and "
        "`pay_panel.items` is the preloaded page of the active tab — switch "
        "tabs with GET bills/occurrences/?status=, which returns the same "
        "rows paginated."
    ),
    parameters=[HomeQuerySerializer],
    responses={
        200: HomeResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)
class HomeAPIView(BaseAPIView):
    """Home dashboard aggregate (E8-S1)."""

    service_class = HomeService

    def get(self, request):
        query = HomeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        result = self.service.build(
            user=request.user,
            tab=query.validated_data.get("tab"),
        )

        return ApiResponse.success(
            data=HomeSerializer(result).data,
            message="Dashboard fetched successfully.",
        )
