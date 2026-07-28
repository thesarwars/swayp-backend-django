from drf_spectacular.utils import extend_schema
from rest_framework.throttling import ScopedRateThrottle

from apps.banking.api.serializers.routing import (
    RoutingValidateSerializer,
    RoutingValidationResultSerializer,
)
from apps.banking.services.routing_service import RoutingValidationService
from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse


@extend_schema(
    tags=["Banking"],
    summary="Validate an ABA routing number",
    description=(
        "Checks the ABA mod-10 checksum and looks up the bank name. Proves "
        "the number is well-formed, not that the account exists — account "
        "verification is the provider's job."
    ),
    request=RoutingValidateSerializer,
    responses={200: RoutingValidationResultSerializer},
)
class RoutingValidateAPIView(BaseAPIView):
    """POST banking/routing/validate/ (E3-S9)."""

    service_class = RoutingValidationService

    # Cheap to call and enumerable, so it is rate limited even though auth is
    # already required.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "routing_validate"

    def post(self, request):
        serializer = RoutingValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = self.service.validate(
            serializer.validated_data["routing_number"]
        )

        return ApiResponse.success(
            data=RoutingValidationResultSerializer(result).data,
            message=result["message"],
        )
