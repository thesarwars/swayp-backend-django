from django.db.models import Q

from .models import Provider


class ProviderRepository:

    @staticmethod
    def get_queryset():
        return (
            Provider.objects
            .select_related("category")
            .filter(status=Provider.Status.ACTIVE)
        )

    def filter(
        self,
        *,
        category_id=None,
        search=None,
    ):
        queryset = self.get_queryset()

        if category_id:
            queryset = queryset.filter(category_id=category_id)

        if search:
            queryset = queryset.filter(
                Q(provider_name__icontains=search)
                | Q(provider_code__icontains=search)
            )

        return queryset.order_by("provider_name")

    def get_by_id(self, provider_id):
        return self.get_queryset().filter(id=provider_id).first()