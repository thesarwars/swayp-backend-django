from drf_spectacular.utils import extend_schema
from rest_framework.throttling import ScopedRateThrottle

from apps.ai_advisor.api.serializers.cash_context import (
    CashContextInputSerializer,
    CashContextSerializer,
)
from apps.ai_advisor.services.cash_context_service import CashContextService
from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse


@extend_schema(
    tags=["Flo (AI advisor)"],
    summary="Cash context for a pending payment",
    description=(
        "Returns {text, figures}. Every figure is computed in Python from "
        "banking balances and bill occurrences; the LLM only phrases the "
        "sentence, and only with live consent and the kill switch on. Render "
        "from `figures` — never parse `text`. Send bill_occurrence_id when "
        "the payment settles a bill, so it is not counted twice."
    ),
    request=CashContextInputSerializer,
    responses=CashContextSerializer,
)
class CashContextAPIView(BaseAPIView):
    """Flo cash context for a pending payment (E7-S2)."""

    # The one endpoint that can cost money per call, and it is cheap to
    # invoke in a loop.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_cash_context"

    def post(self, request):
        payload = CashContextInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        result = CashContextService().build(
            user=request.user,
            amount=payload.validated_data["amount"],
            funding_account_id=payload.validated_data.get(
                "funding_account_id"
            ),
            bill_occurrence_id=payload.validated_data.get(
                "bill_occurrence_id"
            ),
        )

        return ApiResponse.success(
            data=CashContextSerializer(result).data,
            message="Cash context computed.",
        )
