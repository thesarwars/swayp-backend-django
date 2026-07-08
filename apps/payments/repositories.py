from apps.payments.models import Payment
from django.db import transaction

from apps.common.exceptions import NotFoundException
from apps.providers.models import Provider
from apps.bill_categories.models import BillCategory

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

    @staticmethod
    def create(**kwargs):
        return Payment.objects.create(**kwargs)