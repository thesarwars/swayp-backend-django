from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.bills.serializers.bill_serializers import BillCreateSerializer, BillListSerializer, BillUpdateSerializer
from apps.bills.services.bill_service import BillService
from apps.bills.serializers.bill_detail_serializer import BillDetailSerializer

class BillCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillService()

    def post(self, request):
        serializer = BillCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        bill = self.service.create_bill(
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


class BillListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillService()

    def get(self, request):
        bills = self.service.get_user_bills(request.user)

        serializer = BillListSerializer(
            bills,
            many=True,
        )

        return Response(
            {
                "success": True,
                "message": "Bills retrieved successfully.",
                "data": serializer.data,
            }
        )

class BillDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillService()

    def get(self, request, bill_id):
        bill = self.service.get_bill_detail(
            bill_id=bill_id,
            user=request.user,
        )

        serializer = BillDetailSerializer(bill)

        return Response(
            {
                "success": True,
                "message": "Bill details fetched successfully.",
                "data": serializer.data,
            }
        )


    def delete(self, request, bill_id):
        self.service.delete_bill(
            bill_id=bill_id,
            user=request.user,
        )

        return Response(
            {
                "success": True,
                "message": "Bill deleted successfully.",
            }
        )

class BillUpdateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillService()

    def patch(self, request, bill_id):
        serializer = BillUpdateSerializer(
            data=request.data,
            partial=True,
        )

        serializer.is_valid(raise_exception=True)

        bill = self.service.update_bill(
            bill_id=bill_id,
            user=request.user,
            validated_data=serializer.validated_data,
        )

        return Response(
            {
                "success": True,
                "message": "Bill updated successfully.",
                "data": {
                    "id": str(bill.id),
                },
            }
        )
