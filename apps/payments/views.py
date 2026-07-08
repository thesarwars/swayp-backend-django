import traceback

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse

from .schemas import payment_history_schema
from .serializers import (
    PaymentHistoryQuerySerializer,
    PaymentSerializer,
)
from .services import PaymentService


class PaymentHistoryAPIView(BaseAPIView):

    service_class = PaymentService

    @payment_history_schema
    def get(self, request):
        try:
            query = PaymentHistoryQuerySerializer(
                data=request.query_params,
            )

            query.is_valid(raise_exception=True)

            result = self.service.payment_history(
                user=request.user,
                page=query.validated_data["page"],
                page_size=query.validated_data["pageSize"],
                status=query.validated_data.get("status"),
                provider_id=query.validated_data.get("providerId"),
                category_id=query.validated_data.get("categoryId"),
                from_date=query.validated_data.get("fromDate"),
                to_date=query.validated_data.get("toDate"),
                search=query.validated_data.get("search"),
            )

            serializer = PaymentSerializer(
                result["items"],
                many=True,
            )

            return ApiResponse.success(
                data=serializer.data,
                pagination=result["pagination"],
            )

        except Exception as e:
            print("\n" + "=" * 80)
            print("PAYMENT HISTORY ERROR")
            print("=" * 80)
            print(f"Exception Type: {type(e).__name__}")
            print(f"Exception Message: {str(e)}")
            print(traceback.format_exc())
            print("=" * 80 + "\n")

            raise