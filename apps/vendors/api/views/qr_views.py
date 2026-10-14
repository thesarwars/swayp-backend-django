from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.responses import ApiResponse

from apps.vendors.api.serializers.qr import (
    QRDecodeSerializer,
    VendorQRDecodeResponseSerializer,
)
from apps.vendors.services.directory_match import directory_match
from apps.vendors.services.qr_decoder import QRDecodeService


@extend_schema(
    tags=["Vendors"],
    summary="Decode a vendor QR",
    description=(
        "JSON {payload} or multipart image. Bare body. 422 when the QR "
        "cannot be read: ask to scan again."
    ),
    request=QRDecodeSerializer,
    responses={
        200: VendorQRDecodeResponseSerializer,
        422: OpenApiResponse(description="Unreadable QR (code unprocessable)."),
    },
)
class QRDecodeAPIView(APIView):
    """
    POST /vendors/qr/decode/
    Accepts:

    1. JSON
    {
        "payload": "..."
    }
    2. multipart/form-data
    image=<qr image>
    """

    # Bare body, no {success, message, data} (see apps/common/schema.py).
    response_envelope = False

    permission_classes = [IsAuthenticated]

    parser_classes = (
        JSONParser,
        MultiPartParser,
        FormParser,
    )

    def post(self, request):
        serializer = QRDecodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = QRDecodeService()

        try:
            if serializer.validated_data.get("payload"):
                result = service.decode_payload(
                    serializer.validated_data["payload"]
                )
            else:
                result = service.decode_image(
                    serializer.validated_data["image"]
                )

        except ValueError as exc:
            # The standard error envelope, the same as bills/qr/decode
            # (BILLS-2, VEND-10). It was a bare {detail}, so the two routes
            # that share one parser failed in two different shapes.
            return ApiResponse.error(
                message=str(exc),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        match = directory_match(result.get("vendor_name"))

        response = {
            **result,
            "directory_match": match,
        }

        return Response(
            response,
            status=status.HTTP_200_OK,
        )