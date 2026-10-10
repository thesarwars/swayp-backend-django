from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.bills.serializers.bill_serializers import BillCreateSerializer, BillListSerializer, BillUpdateSerializer
from apps.bills.services.bill_service import BillService
from apps.bills.serializers.bill_detail_serializer import BillDetailSerializer
from apps.bills.serializers.bill_review_serializer import (
    BillReviewResponseSerializer,
    BillReviewSerializer,
)
from apps.common.swagger import BAD_REQUEST_RESPONSE, UNAUTHORIZED_RESPONSE
from apps.common.request_meta import request_meta
from apps.payments.idempotency import IdempotencyMixin
from apps.teams.access import AccountScopedMixin

class BillCreateAPIView(AccountScopedMixin, IdempotencyMixin, APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillService()

    @extend_schema(
        tags=["Bills"],
        summary="Create a bill",
        description=(
            "The add-bill wizard's submit. 201 with the review summary for "
            "the closing screen. autopay_mode AUTO needs autopay_consent, "
            "with the text from bills/autopay-authorization/preview."
        ),
        request=BillCreateSerializer,
        responses={
            201: BillReviewResponseSerializer,
            400: BAD_REQUEST_RESPONSE,
            401: UNAUTHORIZED_RESPONSE,
        },
    )
    def post(self, request):
        # A retry must not create a second bill, or with autopay a second
        # debit authorization (API-2).
        return self.run_idempotent(request, lambda: self._create(request))

    def _create(self, request):
        serializer = BillCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        bill = self.service.create_bill(
            user=self.account(request),
            validated_data=serializer.validated_data,
            meta=request_meta(request),
        )

        review = BillReviewSerializer(self.service.review(bill))

        return Response(
            {
                "success": True,
                "message": "Bill created successfully.",
                "data": review.data,
            },
            status=status.HTTP_201_CREATED,
        )


class BillListAPIView(AccountScopedMixin, APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillService()

    @extend_schema(
        tags=["Bills"],
        summary="Bill rules",
        description=(
            "Every bill rule, unpaginated. For the list screen use "
            "bills/occurrences, which pages and filters due dates."
        ),
        responses={200: BillListSerializer(many=True)},
    )
    def get(self, request):
        bills = self.service.get_user_bills(self.account(request))

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

class BillDetailAPIView(AccountScopedMixin, APIView):
    permission_classes = [IsAuthenticated]
    nullable_data = ("DELETE",)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillService()

    @extend_schema(
        tags=["Bills"],
        summary="A bill",
        responses={200: BillDetailSerializer},
    )
    def get(self, request, bill_id):
        bill = self.service.get_bill_detail(
            bill_id=bill_id,
            user=self.account(request),
        )

        serializer = BillDetailSerializer(bill)

        return Response(
            {
                "success": True,
                "message": "Bill details fetched successfully.",
                "data": serializer.data,
            }
        )


    @extend_schema(
        tags=["Bills"],
        summary="Delete a bill",
        description=(
            "200 with data null (not 204). Its open occurrences go and "
            "an autopay authorization is revoked; paid ones stay in history."
        ),
        responses={200: None},
    )
    def delete(self, request, bill_id):
        self.service.delete_bill(
            bill_id=bill_id,
            user=self.account(request),
        )

        return Response(
            {
                "success": True,
                "message": "Bill deleted successfully.",
                "data": None,
            }
        )

class BillUpdateAPIView(AccountScopedMixin, APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillService()

    @extend_schema(
        tags=["Bills"],
        summary="Update a bill",
        description=(
            "Partial: send only what changed. 200 with a refreshed review "
            "summary. On an AUTO bill, changing amount, frequency, "
            "anchor_date, bill_type or payment_method needs a fresh "
            "autopay_consent in the same request."
        ),
        request=BillUpdateSerializer,
        responses={
            200: BillReviewResponseSerializer,
            400: BAD_REQUEST_RESPONSE,
            401: UNAUTHORIZED_RESPONSE,
        },
    )
    def patch(self, request, bill_id):
        serializer = BillUpdateSerializer(
            data=request.data,
            partial=True,
        )

        serializer.is_valid(raise_exception=True)

        bill = self.service.update_bill(
            bill_id=bill_id,
            user=self.account(request),
            validated_data=serializer.validated_data,
            meta=request_meta(request),
        )

        review = BillReviewSerializer(self.service.review(bill))

        return Response(
            {
                "success": True,
                "message": "Bill updated successfully.",
                "data": review.data,
            }
        )
