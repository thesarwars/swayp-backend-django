from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
)
from rest_framework.response import Response
from apps.common.base_views import PublicAPIView
from apps.common.crypto import mask_email

from apps.authentication.api.serializers.password_reset import (
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
)
from apps.authentication.services.forgot_password_service import (
    ForgotPasswordService,
)
from apps.authentication.services.reset_password_service import (
    ResetPasswordService,
)


@extend_schema(
    tags=["Authentication"],
    summary="Forgot Password",
    description="Send password reset OTP.",
    request=ForgotPasswordSerializer,
    responses={
        200: OpenApiResponse(description="OTP sent."),
    },
    examples=[
        OpenApiExample(
            "Forgot Password",
            value={
                "email": "john@gmail.com",
            },
            request_only=True,
        )
    ],
)
class ForgotPasswordView(PublicAPIView):

    def post(self, request):
        serializer = ForgotPasswordSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        ForgotPasswordService.send(
            serializer.user
        )

        email = mask_email(serializer.user.email)

        return Response(
            {
                "success": True,
                "message": f"OTP has been sent to {email}.",
                "data": {"email": email},
            }
        )


@extend_schema(
    tags=["Authentication"],
    summary="Reset Password",
    description=(
        "Set a new password with either the emailed `otp`, or the "
        "`reset_token` that verify-otp returns for a RESET_PASSWORD code. "
        "Send exactly one. A rejected password leaves either usable."
    ),
    request=ResetPasswordSerializer,
    responses={
        200: OpenApiResponse(description="Password reset successful."),
    },
    examples=[
        OpenApiExample(
            "Reset Password",
            value={
                "email": "john@gmail.com",
                "otp": "123456",
                "password": "NewPassword@123",
                # "confirm_password": "NewPassword@123",
            },
            request_only=True,
        )
    ],
)
class ResetPasswordView(PublicAPIView):

    def post(self, request):
        serializer = ResetPasswordSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        ResetPasswordService.reset(
            email=serializer.validated_data["email"],
            otp=serializer.validated_data.get("otp"),
            password=serializer.validated_data["password"],
            reset_token=serializer.validated_data.get("reset_token"),
        )

        return Response(
            {
                "success": True,
                "message": "Password reset successful.",
            }
        )
