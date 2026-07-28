from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.response import Response
from apps.common.base_views import PublicAPIView

from apps.authentication.api.serializers.user_login import (
    LoginSerializer,
    LoginVerifyOTPSerializer,
)
from apps.authentication.services.login_service import LoginService
from apps.authentication.services.login_verify_service import (
    LoginVerifyService,
)


@extend_schema(
    tags=["Authentication"],
    summary="Login",
    description="Validate credentials and send login OTP.",
    request=LoginSerializer,
    responses={
        200: OpenApiResponse(description="OTP sent."),
        400: OpenApiResponse(description="Invalid credentials."),
    },
    examples=[
        OpenApiExample(
            "Login",
            value={
                "email": "john@gmail.com",
                "password": "Password@123",
            },
            request_only=True,
        )
    ],
)
class LoginView(PublicAPIView):

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        LoginService.login(
            serializer.validated_data["user"]
        )

        return Response(
            {
                "success": True,
                "message": "OTP has been sent.",
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Authentication"],
    summary="Verify Login OTP",
    description="Verify login OTP and return JWT tokens.",
    request=LoginVerifyOTPSerializer,
    responses={
        200: OpenApiResponse(description="Login successful."),
        400: OpenApiResponse(description="Invalid OTP."),
    },
    examples=[
        OpenApiExample(
            "Verify Login OTP",
            value={
                "email": "john@gmail.com",
                "otp": "123456",
            },
            request_only=True,
        )
    ],
)
class LoginVerifyOTPView(PublicAPIView):

    def post(self, request):
        serializer = LoginVerifyOTPSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        tokens = LoginVerifyService.verify(
            serializer.validated_data["user"],
            serializer.validated_data["otp_obj"],
            request,
        )

        return Response(
            {
                "success": True,
                "message": "Login successful.",
                "data": tokens,
            },
            status=status.HTTP_200_OK,
        )
