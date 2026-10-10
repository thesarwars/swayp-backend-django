from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.responses import ApiResponse

from apps.providers.models import Provider
from apps.vendors.api.serializers.qr import QRDecodeSerializer
from apps.vendors.services.qr_decoder import QRDecodeService


class QRDecodeAPIView(APIView):

    # Bare body, no {success, message, data} (see apps/common/schema.py).
    response_envelope = False
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

        directory_match = None

        vendor_name = result.get("vendor_name")

        if vendor_name:
            provider = (
                Provider.objects.filter(
                    provider_name__icontains=vendor_name,
                    status=Provider.Status.ACTIVE,
                )
                .select_related("category")
                .only(
                    "id",
                    "provider_name",
                    "category__name",
                    "supports_auto_pay",
                    "status",
                )
                .first()
            )

            if provider:
                directory_match = {
                    "id": str(provider.id),
                    "provider_name": provider.provider_name,
                    "category": provider.category.name if provider.category else None,
                    "supports_auto_pay": provider.supports_auto_pay,
                    "verified": provider.status == Provider.Status.ACTIVE,
                }

        response = {
            **result,
            "directory_match": directory_match,
        }

        return Response(
            response,
            status=status.HTTP_200_OK,
        )