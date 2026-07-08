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
    def list_by_user(
        cls,
        *,
        user,
        status=None,
        provider_id=None,
        category_id=None,
        from_date=None,
        to_date=None,
        search=None,
    ):
        queryset = cls.get_queryset().filter(
            user=user,
        )

        if status:
            queryset = queryset.filter(
                status=status,
            )

        if provider_id:
            queryset = queryset.filter(
                provider_id=provider_id,
            )

        if category_id:
            queryset = queryset.filter(
                category_id=category_id,
            )

        if from_date:
            queryset = queryset.filter(
                created_at__date__gte=from_date,
            )

        if to_date:
            queryset = queryset.filter(
                created_at__date__lte=to_date,
            )

        if search:
            queryset = queryset.filter(
                transaction_reference__icontains=search,
            )

        return queryset.order_by("-created_at")

    @classmethod
    def get_by_id(
        cls,
        *,
        user,
        payment_id,
    ):
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