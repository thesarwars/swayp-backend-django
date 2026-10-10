from apps.bill_categories.models import BillCategory
from apps.common.exceptions import NotFoundException
from apps.payments.models import Payment
from apps.providers.models import Provider


class PaymentRepository:

    @staticmethod
    def get_queryset():
        return (
            Payment.objects
            .select_related(
                "user",
                "provider",
                "category",
                # PAY-3: the history row's vendor and bill, in the same query.
                "vendor",
                "bill_occurrence",
            )
        )

    @staticmethod
    def create(**kwargs):
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

    @classmethod
    def get_for_update(
        cls,
        *,
        payment_id,
        user,
    ):
        try:
            return (
                cls.get_queryset()
                # of=("self",) locks only the payment row. provider and
                # category became nullable in E6-S1, so select_related now
                # emits outer joins and Postgres refuses FOR UPDATE on their
                # nullable side.
                .select_for_update(of=("self",))
                .get(
                    id=payment_id,
                    user=user,
                )
            )
        except Payment.DoesNotExist:
            raise NotFoundException(
                "Payment not found."
            )

    @staticmethod
    def save(
        payment,
        *,
        update_fields=None,
    ):
        payment.save(
            update_fields=update_fields,
        )
        return payment

    @staticmethod
    def update_status(
        *,
        payment,
        status,
        provider_reference=None,
    ):
        payment.status = status

        fields = [
            "status",
            "updated_at",
        ]

        if provider_reference is not None:
            payment.provider_reference = (
                provider_reference
            )
            fields.append(
                "provider_reference"
            )

        payment.save(
            update_fields=fields,
        )

        return payment

    @staticmethod
    def get_provider(provider_id):
        try:
            return Provider.objects.get(
                id=provider_id,
                status="ACTIVE",
            )
        except Provider.DoesNotExist:
            raise NotFoundException(
                "Provider not found."
            )

    @staticmethod
    def get_category(category_id):
        try:
            return BillCategory.objects.get(
                id=category_id,
                is_active=True,
            )
        except BillCategory.DoesNotExist:
            raise NotFoundException(
                "Bill category not found."
            )