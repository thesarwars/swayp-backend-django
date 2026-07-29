"""Payment endpoints (E6-S2 … E6-S6)."""

from drf_spectacular.utils import extend_schema
from rest_framework import status

from apps.common.base_views import BaseAPIView
from apps.common.request_meta import request_meta
from apps.common.responses import ApiResponse
from apps.payments.api.serializers.payment import (
    ConfirmSerializer,
    PaymentCreateSerializer,
    PaymentDetailSerializer,
    PaymentSerializer,
    ResolveSerializer,
)
from apps.payments.idempotency import IdempotencyMixin
from apps.payments.selectors.payment_detail_selector import (
    PaymentDetailSelector,
)
from apps.payments.services.confirm_service import PaymentConfirmService
from apps.payments.services.payment_create_service import PaymentCreateService
from apps.teams.access import RequiresCapability
from apps.teams.permissions import SEND_MONEY
from apps.payments.services.resolution_service import (
    PaymentResolutionService,
)
from rest_framework.exceptions import ValidationError


@extend_schema(
    tags=["Payments"],
    summary="Create payments for selected bills",
    description=(
        "One payment per occurrence, plus a batch when more than one is "
        "selected. Marks the occurrences scheduled so reminders stop, and "
        "returns the authorization text to display. Nothing moves until the "
        "payment is confirmed. Send scheduled_for to future-date it."
    ),
    request=PaymentCreateSerializer,
)
class PaymentCreateAPIView(IdempotencyMixin, BaseAPIView):

    service_class = PaymentCreateService
    idempotency_endpoint = "payments.create"

    def post(self, request):
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def handler():
            result = self.service.create(
                user=request.user,
                occurrence_ids=serializer.validated_data["occurrence_ids"],
                funding_account_id=serializer.validated_data.get(
                    "funding_account_id"
                ),
                rail=serializer.validated_data["rail"],
                scheduled_for=serializer.validated_data.get("scheduled_for"),
                expedited=serializer.validated_data.get("expedited", False),
            )

            payments = result["payments"]

            return ApiResponse.success(
                data={
                    "batch_id": (
                        result["batch"].id if result["batch"] else None
                    ),
                    "payments": PaymentSerializer(payments, many=True).data,
                    "authorization_text": result["authorization_text"],
                    "total": sum(p.total for p in payments),
                },
                message="Payments created. Confirm to authorize.",
                status_code=status.HTTP_201_CREATED,
            )

        return self.run_idempotent(request, handler)


@extend_schema(
    tags=["Payments"],
    summary="Confirm a batch",
    description=(
        "Records one authorization covering every payment in the batch and "
        "starts execution. Re-confirming replays instead of recording a "
        "second consent."
    ),
    request=ConfirmSerializer,
)
class BatchConfirmAPIView(IdempotencyMixin, BaseAPIView):

    service_class = PaymentConfirmService
    idempotency_endpoint = "payments.confirm_batch"
    permission_classes = BaseAPIView.permission_classes + [RequiresCapability]
    required_capability = SEND_MONEY

    def post(self, request, batch_id):
        serializer = ConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def handler():
            result = self.service.confirm_batch(
                user=request.user,
                batch_id=batch_id,
                authorization_text=serializer.validated_data[
                    "authorization_text"
                ],
                meta=request_meta(request),
            )

            return ApiResponse.success(
                data={
                    "batch_id": result["batch"].id,
                    "payments": PaymentSerializer(
                        result["payments"], many=True
                    ).data,
                    "replayed": result["replayed"],
                },
                message=(
                    "Already confirmed."
                    if result["replayed"]
                    else "Payments authorized."
                ),
            )

        return self.run_idempotent(request, handler)


@extend_schema(
    tags=["Payments"],
    summary="Confirm a single payment",
    request=ConfirmSerializer,
)
class PaymentConfirmAPIView(IdempotencyMixin, BaseAPIView):

    service_class = PaymentConfirmService
    idempotency_endpoint = "payments.confirm_payment"
    # A MEMBER can prepare a payment but not authorize it (E10-S1).
    permission_classes = BaseAPIView.permission_classes + [RequiresCapability]
    required_capability = SEND_MONEY

    def post(self, request, payment_id):
        serializer = ConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def handler():
            result = self.service.confirm_payment(
                user=request.user,
                payment_id=payment_id,
                authorization_text=serializer.validated_data[
                    "authorization_text"
                ],
                meta=request_meta(request),
            )

            return ApiResponse.success(
                data=PaymentSerializer(result["payment"]).data,
                message=(
                    "Already confirmed."
                    if result["replayed"]
                    else "Payment authorized."
                ),
            )

        return self.run_idempotent(request, handler)


@extend_schema(
    tags=["Payments"],
    summary="Payment status",
    description="Ordered stage checklist. Poll while the drawer is open.",
)
class PaymentStatusAPIView(BaseAPIView):

    def get(self, request, payment_id):
        selector = PaymentDetailSelector()
        payment = selector.get_payment(request.user, payment_id)

        if payment is None:
            raise ValidationError({"payment": "Payment not found."})

        from apps.payments.api.serializers.payment import (
            PaymentStageSerializer,
        )

        return ApiResponse.success(
            data={
                "payment_id": payment.id,
                "reference": payment.transaction_reference,
                "status": payment.status,
                "stages": PaymentStageSerializer(
                    payment.stages.order_by("order"), many=True
                ).data,
                "progress": selector.progress(payment),
            },
            message="Payment status fetched successfully.",
        )


@extend_schema(
    tags=["Payments"],
    summary="Batch status",
    description="Aggregates its payments; a single failure surfaces.",
)
class BatchStatusAPIView(BaseAPIView):

    def get(self, request, batch_id):
        selector = PaymentDetailSelector()
        batch = selector.get_batch(request.user, batch_id)

        if batch is None:
            raise ValidationError({"batch": "Batch not found."})

        summary = selector.batch_status(batch)
        summary["payments"] = PaymentSerializer(
            summary["payments"], many=True
        ).data

        return ApiResponse.success(
            data=summary,
            message="Batch status fetched successfully.",
        )


@extend_schema(
    tags=["Payments"],
    summary="Payment detail",
    description=(
        "State-aware: stages always, a receipt when settled, a failure block "
        "when it failed."
    ),
    responses={200: PaymentDetailSerializer},
)
class PaymentDetailAPIView(BaseAPIView):

    def get(self, request, payment_id):
        payment = PaymentDetailSelector().get_payment(
            request.user, payment_id
        )

        if payment is None:
            raise ValidationError({"payment": "Payment not found."})

        return ApiResponse.success(
            data=PaymentDetailSerializer(payment).data,
            message="Payment fetched successfully.",
        )


@extend_schema(
    tags=["Payments"],
    summary="Cancel a payment",
    description="Allowed until the cancellation deadline; 409 afterwards.",
)
class PaymentCancelAPIView(BaseAPIView):

    service_class = PaymentConfirmService

    def post(self, request, payment_id):
        payment = self.service.cancel_payment(
            user=request.user, payment_id=payment_id
        )

        return ApiResponse.success(
            data=PaymentSerializer(payment).data,
            message="Payment cancelled.",
        )


@extend_schema(
    tags=["Payments"],
    summary="Cancel a batch",
)
class BatchCancelAPIView(BaseAPIView):

    service_class = PaymentConfirmService

    def post(self, request, batch_id):
        result = self.service.cancel_batch(
            user=request.user, batch_id=batch_id
        )

        return ApiResponse.success(
            data={
                "batch_id": result["batch"].id,
                "cancelled": PaymentSerializer(
                    result["cancelled"], many=True
                ).data,
            },
            message=f"Cancelled {len(result['cancelled'])} payment(s).",
        )


@extend_schema(
    tags=["Payments"],
    summary="Failure detail",
    description=(
        "Reason, the balance at the attempt, days overdue and the vendor's "
        "late-fee countdown."
    ),
)
class PaymentFailureAPIView(BaseAPIView):

    service_class = PaymentResolutionService

    def get(self, request, payment_id):
        return ApiResponse.success(
            data=self.service.failure(
                user=request.user, payment_id=payment_id
            ),
            message="Failure detail fetched successfully.",
        )


@extend_schema(
    tags=["Payments"],
    summary="Resolve a failed payment",
    description=(
        "retry, change_method or reschedule. Always creates a new payment "
        "against the same bill; the failed one stays terminal."
    ),
    request=ResolveSerializer,
)
class PaymentResolveAPIView(IdempotencyMixin, BaseAPIView):

    service_class = PaymentResolutionService
    idempotency_endpoint = "payments.resolve"

    def post(self, request, payment_id):
        serializer = ResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def handler():
            result = self.service.resolve(
                user=request.user,
                payment_id=payment_id,
                action=serializer.validated_data["action"],
                payment_method_id=serializer.validated_data.get(
                    "payment_method_id"
                ),
                funding_account_id=serializer.validated_data.get(
                    "funding_account_id"
                ),
                scheduled_for=serializer.validated_data.get("scheduled_for"),
            )

            return ApiResponse.success(
                data={
                    "action": result["action"],
                    "payment": PaymentSerializer(result["payment"]).data,
                    "replaced_payment_id": result["replaced"].id,
                },
                message=f"Payment {result['action']} scheduled.",
                status_code=status.HTTP_201_CREATED,
            )

        return self.run_idempotent(request, handler)
