from apps.payments.models import Payment


class PaymentRepository:

    @staticmethod
    def get_queryset():
        return (
            Payment.objects
            .select_related(
                "provider",
                "category",
            )
        )

    @classmethod
    def create(cls, **kwargs):
        return Payment.objects.create(**kwargs)

    @classmethod
    def list_by_user(cls, user):
        return (
            cls.get_queryset()
            .filter(user=user)
            .order_by("-created_at")
        )

    @classmethod
    def get_by_id(cls, *, user, payment_id):
        return (
            cls.get_queryset()
            .filter(
                id=payment_id,
                user=user,
            )
            .first()
        )

    @staticmethod
    def save(payment):
        payment.save()
        return payment