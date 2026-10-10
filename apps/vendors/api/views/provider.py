from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.vendors.api.serializers.provider import ProviderSearchSerializer
from apps.vendors.services.directory_service import DirectoryService


@extend_schema(
    tags=["Vendors"],
    summary="Search the biller directory",
    description=(
        "Billers reachable on the network rail. To add one: POST /vendors "
        "with name, category = category_id (omit if null), source DIRECTORY "
        "and payment_method { method_type NETWORK, network_payee_ref = "
        "external_id }."
    ),
    parameters=[
        OpenApiParameter("q", str, description="Biller name to search for"),
    ],
)
class ProviderDirectorySearchAPIView(ListAPIView):

    # Bare body, no {success, message, data} (see apps/common/schema.py).
    response_envelope = False
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
