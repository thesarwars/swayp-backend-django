from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .dtos import WalletSummaryResponseDTO
from .services import WalletService


class WalletSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = WalletService.get_summary(request.user)

        serializer = WalletSummaryResponseDTO(wallet)

        return Response(serializer.data, status=status.HTTP_200_OK)