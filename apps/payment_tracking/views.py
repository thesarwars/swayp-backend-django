from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse

from .schemas import payment_tracking_schema
from .serializers import (
    PaymentTrackingQuerySerializer,
    PaymentTrackingSerializer,
)
from .services import PaymentTrackingService


class PaymentTrackingAPIView(BaseAPIView):

    service_class = PaymentTrackingService

    @payment_tracking_schema
    def get(self, request):
        query = PaymentTrackingQuerySerializer(
            data=request.query_params,
        )

        query.is_valid(raise_exception=True)

        result = self.service.list_tracking(
            user=request.user,
            page=query.validated_data["page"],
            page_size=query.validated_data["pageSize"],
        )

        serializer = PaymentTrackingSerializer(
            result["items"],
            many=True,
        )

        return ApiResponse.success(
            data=serializer.data,
            pagination=result["pagination"],
        )