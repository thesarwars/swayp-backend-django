from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.api.serializers.token import (
    LogoutSerializer,
    RefreshSerializer,
)
from apps.authentication.services.logout_service import (
    LogoutService,
)
from apps.authentication.services.refresh_token_service import (
    RefreshTokenService,
)


@extend_schema(
    tags=["Authentication"],
    summary="Refresh Access Token",
    description="Generate a new access token using a refresh token.",
    request=RefreshSerializer,
    responses={
        200: OpenApiResponse(description="Token refreshed."),
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
class RefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RefreshSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        tokens = RefreshTokenService.refresh(
            serializer.validated_data["refresh"]
        )

        return Response(
            {
                "success": True,
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
class LogoutView(APIView):
    permission_classes = [AllowAny]

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
