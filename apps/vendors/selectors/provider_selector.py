from django.db.models import Q

from apps.providers.models import Provider


class ProviderSelector:

    @staticmethod
    def search(query):

        queryset = Provider.objects.filter(
            status=Provider.Status.ACTIVE
        )

        if query:
            queryset = queryset.filter(
                Q(provider_name__icontains=query)
                | Q(provider_code__icontains=query)
            )

        return queryset.select_related("category").order_by("provider_name")