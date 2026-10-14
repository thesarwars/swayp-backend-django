from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.users.api.serializers.options import FormOptionsSerializer
from apps.users.options import (
    BUSINESS_SIZES,
    BUSINESS_TYPES,
    INDUSTRIES,
    as_options,
)


@extend_schema(
    tags=["Users"],
    summary="Form choice lists",
    description=(
        "Industries, business sizes and business types for the sign-up and "
        "settings forms. Send `value`, show `label`. Public: sign-up needs "
        "it before there is a token. The fields still accept free text."
    ),
    auth=[],
    responses={200: FormOptionsSerializer},
)
class FormOptionsAPIView(BaseAPIView):

    permission_classes = [AllowAny]

    def get(self, request):
        return ApiResponse.success(
            data=FormOptionsSerializer({
                "industries": as_options(INDUSTRIES),
                "business_sizes": as_options(BUSINESS_SIZES),
                "business_types": as_options(BUSINESS_TYPES),
            }).data,
            message="Options fetched successfully.",
        )
