"""Price and date every rail before a payment exists (PAY-5)."""

from drf_spectacular.utils import extend_schema

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.common.swagger import BAD_REQUEST_RESPONSE, UNAUTHORIZED_RESPONSE
from apps.payments.api.serializers.quote import (
    PaymentQuoteRequestSerializer,
    PaymentQuoteResponseSerializer,
    PaymentQuoteSerializer,
)
from apps.payments.services.quote_service import PaymentQuoteService
from apps.teams.access import AccountScopedMixin


@extend_schema(
    tags=["Payments"],
    summary="Quote rails for selected bills",
    description=(
        "For each occurrence: every rail, whether this bill can use it (and "
        "why not), its fee, and when it would start and arrive, plus the "
        "expedited option for checks. default_rail is what POST /payments "
        "uses when rail is omitted. Creates and charges nothing."
    ),
    request=PaymentQuoteRequestSerializer,
    responses={
        200: PaymentQuoteResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)
class PaymentQuoteAPIView(AccountScopedMixin, BaseAPIView):

    service_class = PaymentQuoteService

    def post(self, request):
        serializer = PaymentQuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quote = self.service.quote(
            user=self.account(request),
            occurrence_ids=serializer.validated_data["occurrence_ids"],
            scheduled_for=serializer.validated_data.get("scheduled_for"),
        )

        return ApiResponse.success(
            data=PaymentQuoteSerializer(quote).data,
            message="Quote ready.",
        )
