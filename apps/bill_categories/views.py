from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .dtos import BillCategoryResponseDTO
from .services import BillCategoryService
from drf_spectacular.utils import (
    extend_schema,
    OpenApiResponse,
)




@extend_schema(
    tags=["Bill Categories"],
    summary="List Bill Categories",
    description="""
Returns all bill categories shown on the dashboard.

Authentication Required.
""",
    responses={
        200: OpenApiResponse(
            description="Bill categories fetched successfully."
        ),
        401: OpenApiResponse(
            description="Authentication credentials were not provided."
        ),
    },
)

class BillCategoryListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillCategoryService()

    def get(self, request):
        categories = self.service.get_dashboard_categories()

        response = [
            BillCategoryResponseDTO(
                id=item["id"],
                name=item["name"],
                icon=item["icon"],
                color=item["color"],
                displayOrder=item["displayOrder"],
            ).to_dict()
            for item in categories
        ]

        return Response(
            {
                "success": True,
                "data": response,
            }
        )