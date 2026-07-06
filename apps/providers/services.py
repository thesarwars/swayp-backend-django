from apps.common.pagination import PaginationService

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

        result = PaginationService.paginate(
            queryset=queryset,
            page=page,
            page_size=page_size,
        )

        providers = []

        for provider in result["items"]:
            providers.append(
                {
                    "id": provider.id,
                    "categoryId": provider.category.id,
                    "categoryName": provider.category.name,
                    "providerName": provider.provider_name,
                    "providerCode": provider.provider_code,
                    "logo": provider.logo,
                    "description": provider.description,
                    "country": provider.country,
                    "supportsAutoPay": provider.supports_auto_pay,
                }
            )

        return {
            "items": providers,
            "pagination": result["pagination"],
        }