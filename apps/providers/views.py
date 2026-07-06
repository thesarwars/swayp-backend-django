from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .dtos import ProviderResponseDTO
from .services import ProviderService


class ProviderListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = ProviderService()

    def get(self, request):
        page = int(request.GET.get("page", 1))
        page_size = int(request.GET.get("pageSize", 20))

        result = self.service.list_providers(
            category_id=request.GET.get("categoryId"),
            search=request.GET.get("search"),
            page=page,
            page_size=page_size,
        )

        providers = [
            ProviderResponseDTO(
                id=item["id"],
                categoryId=item["category"]["id"],
                categoryName=item["category"]["name"],
                providerName=item["providerName"],
                providerCode=item["providerCode"],
                logo=item["logo"],
                description=item["description"],
                country=item["country"],
                supportsAutoPay=item["supportsAutoPay"],
            ).to_dict()
            for item in result["items"]
        ]

        return Response(
            {
                "success": True,
                "data": providers,
                "pagination": result["pagination"],
            }
        )