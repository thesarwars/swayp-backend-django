from apps.payment_tracking.models import (
    PaymentTracking,
)


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

    @classmethod
    def list_by_user(
        cls,
        *,
        user,
    ):
        return (
            cls.get_queryset()
            .filter(
                payment__user=user,
            )
            .order_by("-created_at")
        )

    @classmethod
    def get_by_payment(
        cls,
        *,
        user,
        payment_id,
    ):
        return (
            cls.get_queryset()
            .filter(
                payment__user=user,
                payment_id=payment_id,
            )
            .first()
        )

    @staticmethod
    def create(**kwargs):
        return PaymentTracking.objects.create(
            **kwargs
        )

    @classmethod
    def get_by_payment_for_update(
        cls,
        *,
        payment,
    ):
        return (
            cls.get_queryset()
            .select_for_update()
            .get(
                payment=payment,
            )
        )

    @staticmethod
    def update_status(
        *,
        tracking,
        status,
        estimated_completion=None,
    ):
        tracking.status = status

        fields = [
            "status",
            "updated_at",
        ]

        if estimated_completion is not None:
            tracking.estimated_completion = (
                estimated_completion
            )
            fields.append(
                "estimated_completion"
            )

        tracking.save(
            update_fields=fields,
        )

        return tracking