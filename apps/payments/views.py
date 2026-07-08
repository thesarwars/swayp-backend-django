import traceback

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse

from .schemas import payment_history_schema, payment_success_schema
from .serializers import (
    PaymentHistoryQuerySerializer,
    PaymentSerializer,
)
from .services import PaymentService
from apps.bill_categories.repositories import BillCategoryRepository
from apps.providers.repositories import ProviderRepository

from .serializers import (
    CreatePaymentSerializer,
)
from .schemas import (
    payment_processing_schema,
)
from .schemas import create_payment_schema


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




class CreatePaymentAPIView(BaseAPIView):

    service_class = PaymentService

    @create_payment_schema
    def post(self, request):
        serializer = CreatePaymentSerializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        payment = self.service.create_payment(
            user=request.user,
            provider_id=serializer.validated_data["providerId"],
            category_id=serializer.validated_data["categoryId"],
            amount=serializer.validated_data["amount"],
            payment_method=serializer.validated_data["paymentMethod"],
        )

        return ApiResponse.success(
            message="Payment created successfully.",
            data=PaymentSerializer(payment).data,
            status_code=201,
        )
    

class PaymentProcessingAPIView(
    BaseAPIView,
):
    service_class = PaymentService

    @payment_processing_schema
    def patch(
        self,
        request,
        payment_id,
    ):
        self.service.mark_processing(
            user=request.user,
            payment_id=payment_id,
        )

        return ApiResponse.success(
            message="Payment is now processing.",
        )
    


class PaymentSuccessAPIView(
    BaseAPIView,
):
    service_class = PaymentService

    @payment_success_schema
    def patch(
        self,
        request,
        payment_id,
    ):
        self.service.mark_successful(
            user=request.user,
            payment_id=payment_id,
        )

        return ApiResponse.success(
            message="Payment marked as successful.",
        )