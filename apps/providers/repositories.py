from django.db.models import Q

from .models import Provider


class ProviderRepository:
    @staticmethod
    def get_all():
        return (
            Provider.objects.select_related("category")
            .filter(status=Provider.Status.ACTIVE)
        )

    @staticmethod
    def filter(
        *,
        category_id=None,
        search=None,
    ):
        queryset = ProviderRepository.get_all()

        if category_id:
            queryset = queryset.filter(category_id=category_id)

        if search:
            queryset = queryset.filter(
                Q(provider_name__icontains=search)
                | Q(provider_code__icontains=search)
            )

        return queryset.order_by("provider_name")

    @staticmethod
    def get_by_id(provider_id):
        return (
            ProviderRepository.get_all()
            .filter(id=provider_id)
            .first()
        )