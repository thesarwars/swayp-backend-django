from rest_framework import status
from rest_framework.response import Response

from apps.ai_advisor.api.serializers.cash_context import (
    CashContextInputSerializer,
    CashContextSerializer,
)
from apps.ai_advisor.services.cash_context_service import CashContextService
from apps.common.base_views import BaseAPIView


class CashContextAPIView(BaseAPIView):
    """Flo cash context for a pending payment (E7-S2)."""

    def post(self, request):
        payload = CashContextInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        result = CashContextService().build(
            user=request.user,
            amount=payload.validated_data["amount"],
            funding_account_id=payload.validated_data.get(
                "funding_account_id"
            ),
        )

        return Response(
            CashContextSerializer(result).data, status=status.HTTP_200_OK
        )
