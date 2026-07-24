from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.bill_categories.serializers.bill_serializers import BillCreateSerializer
from apps.bill_categories.services.bill_service import BillService


class BillCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = BillCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        bill = BillService.create_bill(
            user=request.user,
            validated_data=serializer.validated_data,
        )

        return Response(
            {
                "success": True,
                "message": "Bill created successfully.",
                "data": {
                    "id": str(bill.id),
                },
            },
            status=status.HTTP_201_CREATED,
        )