"""Bill QR decode (E4-S7)."""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.bills.serializers.qr_serializer import (
    BillQRDecodeResponseSerializer,
    BillQRPrefillSerializer,
)
from apps.bills.services.qr_service import BillQRService
from apps.common.responses import ApiResponse
from apps.common.swagger import BAD_REQUEST_RESPONSE, UNAUTHORIZED_RESPONSE
from apps.teams.access import AccountScopedMixin
from apps.vendors.api.serializers.qr import QRDecodeSerializer


@extend_schema(
    tags=["Bills"],
    summary="Decode a bill QR",
    description=(
        "Decodes a QR into bill-wizard prefill fields. Shares one parser with "
        "the vendor QR endpoint — there is no second implementation. "
        "vendor_id and category_id are matched by exact name and are null "
        "when nothing matches. An unreadable QR is 422 with the standard "
        "{success: false, message} body."
    ),
    request=QRDecodeSerializer,
    responses={
        200: BillQRDecodeResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        422: OpenApiResponse(
            description="Unreadable payload: ask to scan again "
            "(code unprocessable)."
        ),
        401: UNAUTHORIZED_RESPONSE,
    },
)
class BillQRDecodeAPIView(AccountScopedMixin, APIView):

    permission_classes = [IsAuthenticated]
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillQRService()

    def post(self, request):
        serializer = QRDecodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = self.service.decode(
                user=self.account(request),
                payload=serializer.validated_data.get("payload"),
                image=serializer.validated_data.get("image"),
            )
        except ValueError as exc:
            return ApiResponse.error(
                message=str(exc),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return ApiResponse.success(
            data=BillQRPrefillSerializer(result).data,
            message="QR decoded successfully.",
        )
