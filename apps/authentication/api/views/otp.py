from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.api.serializers.otp import (
    ResendOTPSerializer,
)
from apps.authentication.services.resend_otp_service import (
    ResendOTPService,
)


@extend_schema(
    tags=["Authentication"],
    summary="Resend OTP",
    description="Generate and resend OTP.",
    request=ResendOTPSerializer,
    responses={
        200: OpenApiResponse(description="OTP sent."),
    },
    examples=[
        OpenApiExample(
            "Resend OTP",
            value={
                "email": "john@gmail.com",
                "purpose": "LOGIN",
            },
            request_only=True,
        )
    ],
)
class ResendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResendOTPSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        ResendOTPService.resend(
            serializer.validated_data["user"],
            serializer.validated_data["purpose"],
        )

        return Response(
            {
                "success": True,
                "message": "OTP sent successfully.",
            },
            status=status.HTTP_200_OK,
        )
