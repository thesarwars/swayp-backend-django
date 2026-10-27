from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.response import Response
from rest_framework.exceptions import APIException
from rest_framework_simplejwt.exceptions import TokenError
from apps.common.base_views import PublicAPIView

from apps.authentication.api.serializers.token import (
    LogoutSerializer,
    RefreshSerializer,
    TokenPairSerializer,
)
from apps.authentication.services.logout_service import (
    LogoutService,
)
from apps.authentication.services.refresh_token_service import (
    RefreshTokenService,
)



class RefreshTokenInvalid(APIException):
    """401 with code token_not_valid: sign in again.

    Not simplejwt's InvalidToken: that is an AuthenticationFailed, which DRF
    turns into a 403 on a view with no authentication scheme, and this one
    is public by necessity.
    """

    status_code = 401
    default_detail = "Token is invalid or expired."
    default_code = "token_not_valid"

@extend_schema(
    tags=["Authentication"],
    summary="Refresh Access Token",
    description="Generate a new access token using a refresh token.",
    request=RefreshSerializer,
    responses={
        200: TokenPairSerializer,
    },
    examples=[
        OpenApiExample(
            "Refresh Token",
            value={
                "refresh": "your_refresh_token",
            },
            request_only=True,
        )
    ],
)
class RefreshView(PublicAPIView):

    def post(self, request):
        serializer = RefreshSerializer(
            data=request.data
        )

        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as error:
            # What simplejwt's own view does: an expired, malformed or
            # already-rotated token is a 401 (token_not_valid), not a 500.
            raise RefreshTokenInvalid(error.args[0]) from error

        try:
            tokens = RefreshTokenService.refresh(
                serializer.validated_data, request=request
            )
        except TokenError as error:
            # The session was signed out from another device.
            raise RefreshTokenInvalid(error.args[0]) from error

        return Response(
            {
                "success": True,
                "message": "Token refreshed.",
                "data": tokens,
            }
        )


@extend_schema(
    tags=["Authentication"],
    summary="Logout",
    description="Logout current session.",
    request=LogoutSerializer,
    responses={
        204: OpenApiResponse(description="Logged out."),
    },
    examples=[
        OpenApiExample(
            "Logout",
            value={
                "refresh": "your_refresh_token",
            },
            request_only=True,
        )
    ],
)
class LogoutView(PublicAPIView):

    def post(self, request):
        serializer = LogoutSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        LogoutService.logout(
            serializer.validated_data["refresh"]
        )

        return Response(
            status=status.HTTP_204_NO_CONTENT
        )
