from apps.common.pagination import PaginationService

from apps.providers.repositories import ProviderRepository


class ProviderSelector:
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

        return PaginationService.paginate(
            queryset=queryset,
            page=page,
            page_size=page_size,
        )

    def get_provider(self, provider_id):
        return self.repository.get_by_id(provider_id)