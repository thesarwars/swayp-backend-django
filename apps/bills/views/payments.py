"""Bill payment history (E4-S4)."""

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.bills.serializers.bill_payment_history_serializer import (
    BillPaymentHistorySerializer,
)
from apps.bills.services.bill_service import BillService
from apps.common.pagination import StandardPagination
from apps.common.responses import ApiResponse


@extend_schema(
    tags=["Bills"],
    summary="Bill payment history",
    description=(
        "Payments for this bill, joined through its occurrences. A retry is a "
        "separate payment against the same occurrence and appears as its own "
        "row."
    ),
    responses={200: BillPaymentHistorySerializer(many=True)},
)
class BillPaymentHistoryAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillService()

    def get(self, request, bill_id):
        queryset = self.service.payment_history(
            bill_id=bill_id,
            user=request.user,
        )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)

        serializer = BillPaymentHistorySerializer(page, many=True)

        body = paginator.get_paginated_response(serializer.data).data

        return ApiResponse.success(
            data=body["items"],
            message="Payment history fetched successfully.",
            pagination=body["pagination"],
        )
