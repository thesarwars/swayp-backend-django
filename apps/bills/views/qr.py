"""Bill QR decode (E4-S7)."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.bills.services.qr_service import BillQRService
from apps.common.responses import ApiResponse
from apps.vendors.api.serializers.qr import QRDecodeSerializer


@extend_schema(
    tags=["Bills"],
    summary="Decode a bill QR",
    description=(
        "Decodes a QR into bill-wizard prefill fields. Shares one parser with "
        "the vendor QR endpoint — there is no second implementation."
    ),
    request=QRDecodeSerializer,
)
class BillQRDecodeAPIView(APIView):

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
                payload=serializer.validated_data.get("payload"),
                image=serializer.validated_data.get("image"),
            )
        except ValueError as exc:
            return ApiResponse.error(
                message=str(exc),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return ApiResponse.success(
            data=result,
            message="QR decoded successfully.",
        )
