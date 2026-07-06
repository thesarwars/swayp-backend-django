from django.core.paginator import Paginator

from .repositories import ProviderRepository


class ProviderService:
    def __init__(self):
        self.repository = ProviderRepository()

    def list_providers(
        self,
        *,
        category_id=None,
        search=None,
        page=1,
        page_size=20,
    ):
        queryset = self.repository.filter(
            category_id=category_id,
            search=search,
        )

        paginator = Paginator(queryset, page_size)
        result = paginator.get_page(page)

        return {
            "items": [
                {
                    "id": str(provider.id),
                    "providerName": provider.provider_name,
                    "providerCode": provider.provider_code,
                    "logo": provider.logo,
                    "description": provider.description,
                    "country": provider.country,
                    "supportsAutoPay": provider.supports_auto_pay,
                    "category": {
                        "id": str(provider.category.id),
                        "name": provider.category.name,
                    },
                }
                for provider in result
            ],
            "pagination": {
                "page": result.number,
                "pageSize": page_size,
                "totalPages": paginator.num_pages,
                "totalItems": paginator.count,
                "hasNext": result.has_next(),
                "hasPrevious": result.has_previous(),
            },
        }