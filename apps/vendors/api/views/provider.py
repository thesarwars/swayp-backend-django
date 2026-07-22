from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from apps.vendors.selectors.provider_selector import ProviderSelector
from apps.vendors.api.serializers.provider import ProviderSearchSerializer


class ProviderDirectorySearchAPIView(ListAPIView):

    serializer_class = ProviderSearchSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        query = self.request.query_params.get("q", "").strip()
        return ProviderSelector.search(query)