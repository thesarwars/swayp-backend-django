from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.response import Response
from apps.common.base_views import PublicAPIView
from apps.common.crypto import mask_email

from apps.authentication.api.serializers.user_login import LoginSerializer
from apps.authentication.services.login_service import LoginService


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

        user = serializer.validated_data["user"]

        LoginService.login(user)

        email = mask_email(user.email)

        return Response(
            {
                "success": True,
                "message": f"OTP has been sent to {email}.",
                "data": {"email": email},
            },
            status=status.HTTP_200_OK,
        )


# LoginVerifyOTPView is gone: the login code is verified by the merged view in
# views/otp.py, which dispatches to LoginVerifyService on a LOGIN code so the
# refresh token is still recorded against a user agent and an IP.
