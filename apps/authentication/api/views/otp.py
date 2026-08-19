from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.response import Response
from apps.common.base_views import PublicAPIView
from apps.common.crypto import mask_email

from apps.authentication.api.serializers.otp import (
    ResendOTPSerializer,
    VerifyOTPSerializer,
)
from apps.authentication.services.resend_otp_service import (
    ResendOTPService,
)
from apps.authentication.services.verify_otp_service import (
    VerifyOTPService,
)


@extend_schema(
    tags=["Authentication"],
    summary="Verify OTP",
    description=(
        "Verify the registration OTP, activate the account and return JWT "
        "tokens. There is no login OTP — a password signs in on its own — so "
        "REGISTRATION is the only `purpose` this accepts."
    ),
    request=VerifyOTPSerializer,
    responses={
        200: OpenApiResponse(description="Verified."),
        400: OpenApiResponse(description="Invalid OTP."),
    },
    examples=[
        OpenApiExample(
            "Verify OTP",
            value={
                "email": "john@gmail.com",
                "otp": "123456",
            },
            request_only=True,
        ),
    ],
)
class VerifyOTPView(PublicAPIView):

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        otp_obj = serializer.validated_data["otp_obj"]

        tokens = VerifyOTPService.verify(user, otp_obj)

        return Response(
            {
                "success": True,
                "message": "Account verified successfully.",
                # purpose is still echoed: it was here when this endpoint
                # answered for two flows, and dropping a key breaks clients
                # that read it for no gain.
                "data": {"purpose": otp_obj.purpose, **tokens},
            },
            status=status.HTTP_200_OK,
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
                "purpose": "REGISTRATION",
            },
            request_only=True,
        )
    ],
)
class ResendOTPView(PublicAPIView):

    def post(self, request):
        serializer = ResendOTPSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]

        ResendOTPService.resend(
            user,
            serializer.validated_data["purpose"],
            channel=serializer.validated_data.get("channel"),
        )

        email = mask_email(user.email)

        return Response(
            {
                "success": True,
                "message": f"OTP has been sent to {email}.",
                "data": {"email": email},
            },
            status=status.HTTP_200_OK,
        )
