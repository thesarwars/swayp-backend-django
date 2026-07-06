from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .dtos import BillCategoryResponseDTO
from .services import BillCategoryService


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