"""The autopay authorization text, written by the server (BILLS-3)."""

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.bills.serializers.autopay_authorization_serializer import (
    AutopayAuthorizationPreviewSerializer,
    AutopayAuthorizationResponseSerializer,
)
from apps.bills.services.autopay_authorization_service import (
    AutopayAuthorizationService,
)
from apps.common.responses import ApiResponse
from apps.common.swagger import BAD_REQUEST_RESPONSE, UNAUTHORIZED_RESPONSE
from apps.teams.access import AccountScopedMixin


@extend_schema(
    tags=["Bills"],
    summary="Autopay authorization text",
    description=(
        "The exact text a user agrees to when turning autopay on, written "
        "from the terms being authorized. Show it, and send it back verbatim "
        "as autopay_consent.authorization_text on bill create or update. "
        "Call it again whenever the terms change. Creates nothing."
    ),
    request=AutopayAuthorizationPreviewSerializer,
    responses={
        200: AutopayAuthorizationResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)
class AutopayAuthorizationPreviewAPIView(AccountScopedMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AutopayAuthorizationPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = AutopayAuthorizationService().preview(
            user=self.account(request), terms=serializer.validated_data
        )

        return ApiResponse.success(
            data=data, message="Authorization text generated."
        )
