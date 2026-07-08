from .models import PaymentTracking


class PaymentTrackingRepository:

    @staticmethod
    def get_queryset():
        return (
            PaymentTracking.objects
            .select_related(
                "payment",
                "payment__provider",
                "payment__user",
            )
        )

    def list_by_user(self, user):
        return (
            self.get_queryset()
            .filter(
                payment__user=user,
            )
            .order_by("-created_at")
        )

    def get_by_payment(
        self,
        *,
        user,
        payment_id,
    ):
        return (
            self.get_queryset()
            .filter(
                payment_id=payment_id,
                payment__user=user,
            )
            .first()
        )

    def create(self, **kwargs):
        return PaymentTracking.objects.create(**kwargs)

    def save(self, tracking):
        tracking.save()
        return tracking


    def get_by_payment_for_update(
        self,
        *,
        payment,
    ):
        return (
            PaymentTracking.objects
            .select_for_update()
            .get(
                payment=payment,
            )
        )

    def save(self, tracking):
        tracking.save(
            update_fields=[
                "status",
                "estimated_completion",
                "updated_at",
            ]
        )

        return tracking