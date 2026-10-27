from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.response import Response
from apps.common.base_views import PublicAPIView

from apps.authentication.api.serializers.token import SignInSerializer
from apps.authentication.api.serializers.user_login import LoginSerializer
from apps.authentication.services.login_service import LoginService


@extend_schema(
    tags=["Authentication"],
    summary="Login",
    description=(
        "Validate credentials and return JWT tokens. With two-step "
        "verification on, mfa_required is true, access and refresh are "
        "null, and the sign-in finishes at auth/login/mfa with mfa_token."
    ),
    request=LoginSerializer,
    responses={
        200: SignInSerializer,
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

        # The serializer has already refused a locked, inactive or unverified
        # account, so reaching here is the login.
        tokens = LoginService.sign_in(user, request)

        return Response(
            {
                "success": True,
                "message": "Login successful.",
                "data": tokens,
            },
            status=status.HTTP_200_OK,
        )


# LoginVerifyOTPView is gone. It verified the emailed login code, and there is
# no longer one to verify — /auth/verify-otp finishes registration only, and
# the phone flow keeps its own verify at /auth/login/phone/verify.
