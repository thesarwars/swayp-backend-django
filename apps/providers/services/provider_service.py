from apps.providers.selectors.provider_selector import ProviderSelector


class ProviderService:
    def __init__(self):
        self.selector = ProviderSelector()

    def list_providers(
        self,
        *,
        category_id=None,
        search=None,
        page=1,
        page_size=20,
    ):
        return self.selector.list_providers(
            category_id=category_id,
            search=search,
            page=page,
            page_size=page_size,
        )