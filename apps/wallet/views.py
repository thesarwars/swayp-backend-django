from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse

from .schemas import wallet_summary_schema
from .serializers import WalletSummarySerializer
from .services import WalletService


class WalletSummaryAPIView(BaseAPIView):

    service_class = WalletService

    @wallet_summary_schema
    def get(self, request):
        wallet = self.service.get_summary(
            request.user
        )

        serializer = WalletSummarySerializer(
            wallet
        )

        return ApiResponse.success(
            data=serializer.data
        )