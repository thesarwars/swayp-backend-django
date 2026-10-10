"""Bill invoice (E4-S7)."""

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.bills.serializers.bill_invoice_serializer import (
    BillInvoiceSerializer,
)
from apps.bills.services.bill_service import BillService
from apps.bills.services.invoice_service import InvoiceService
from apps.common.responses import ApiResponse
from apps.teams.access import AccountScopedMixin


@extend_schema(
    tags=["Bills"],
    summary="Bill invoice",
    description=(
        "Invoice fields for the modal, rendered from bill data only — no OCR "
        "in v1. Includes the payment reference the invoice QR encodes."
    ),
    responses={200: BillInvoiceSerializer},
)
class BillInvoiceAPIView(AccountScopedMixin, APIView):

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillService()
        self.invoice_service = InvoiceService()

    def get(self, request, bill_id):
        bill = self.service.get_bill_detail(
            bill_id=bill_id,
            user=self.account(request),
        )

        return ApiResponse.success(
            # Serialized so amount is a money string, not a float.
            data=BillInvoiceSerializer(self.invoice_service.build(bill)).data,
            message="Invoice fetched successfully.",
        )
