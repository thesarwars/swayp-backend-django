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

        return PaginationService.paginate(
            queryset=queryset,
            page=page,
            page_size=page_size,
        )