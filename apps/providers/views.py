from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .dtos import ProviderResponseDTO
from .services import ProviderService
from drf_spectacular.utils import (
    extend_schema,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
)




@extend_schema(
    tags=["Providers"],
    summary="List Providers",
    description="""
Returns providers.

Supports filtering by category and searching by provider name.
""",
    parameters=[
        OpenApiParameter(
            name="categoryId",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            description="Bill Category ID",
        ),
        OpenApiParameter(
            name="search",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            description="Search provider name",
        ),
        OpenApiParameter(
            name="page",
            type=OpenApiTypes.INT,
            default=1,
            location=OpenApiParameter.QUERY,
        ),
        OpenApiParameter(
            name="pageSize",
            type=OpenApiTypes.INT,
            default=20,
            location=OpenApiParameter.QUERY,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Providers fetched successfully."
        ),
        401: OpenApiResponse(
            description="Unauthorized."
        ),
    },
)
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
    



@extend_schema(
    tags=["Providers"],
    summary="Search Providers",
    description="Search providers by keyword.",
    parameters=[
        OpenApiParameter(
            name="q",
            type=OpenApiTypes.STR,
            required=True,
            location=OpenApiParameter.QUERY,
            description="Search keyword",
        ),
        OpenApiParameter(
            name="page",
            type=OpenApiTypes.INT,
            default=1,
            location=OpenApiParameter.QUERY,
        ),
        OpenApiParameter(
            name="pageSize",
            type=OpenApiTypes.INT,
            default=20,
            location=OpenApiParameter.QUERY,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Providers fetched successfully."
        ),
    },
)
class ProviderSearchAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = ProviderService()

    def get(self, request):
        q = request.query_params.get("q", "").strip()

        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("pageSize", 20))

        result = self.service.list_providers(
            search=q,
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