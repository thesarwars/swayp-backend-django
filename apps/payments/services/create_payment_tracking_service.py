from apps.common.enums import PaymentStatus

from apps.payments.models import PaymentTracking


class CreatePaymentTrackingService:

    def execute(
        self,
        *,
        payment,
        estimated_completion=None,
    ):
        return PaymentTracking.objects.create(
            payment=payment,
            status=PaymentStatus.PENDING,
            provider=payment.provider.provider_name,
            amount=payment.amount,
            reference=payment.transaction_reference,
            estimated_completion=estimated_completion,
        )