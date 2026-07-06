from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .dtos import WalletSummaryResponseDTO
from .services import WalletService
from drf_spectacular.utils import (
    extend_schema,
    OpenApiResponse,
)


@extend_schema(
    tags=["Wallet"],
    summary="Wallet Summary",
    description="""
Returns the authenticated user's wallet summary.

Includes:

- Current balance
- Currency
- Last updated time
- Wallet status
""",
    responses={
        200: OpenApiResponse(
            description="Wallet summary retrieved successfully."
        ),
        401: OpenApiResponse(
            description="Unauthorized."
        ),
    },
)
class WalletSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = WalletService.get_summary(request.user)

        serializer = WalletSummaryResponseDTO(wallet)

        return Response(serializer.data, status=status.HTTP_200_OK)