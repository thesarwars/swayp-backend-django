from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.vendors.api.serializers.provider import ProviderSearchSerializer
from apps.vendors.services.directory_service import DirectoryService


class ProviderDirectorySearchAPIView(ListAPIView):
    """Configured-account directory search — behind the DirectoryProvider
    interface (mock today), paginated, with the verified/network badges."""

    serializer_class = ProviderSearchSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # pragma: no cover - results come from the provider
        return []

    def list(self, request, *args, **kwargs):
        query = request.query_params.get("q", "").strip()
        results = DirectoryService.search(query)

        page = self.paginate_queryset(results)
        target = page if page is not None else results
        serializer = self.get_serializer(target, many=True)

        if page is not None:
            return self.get_paginated_response(serializer.data)

        return Response(serializer.data)
