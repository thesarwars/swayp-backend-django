"""Payment endpoints (E6-S2 … E6-S6)."""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status

from apps.common.base_views import BaseAPIView
from apps.common.request_meta import request_meta
from apps.common.enums import PaymentStatus
from apps.common.responses import ApiResponse
from apps.payments.api.serializers.payment import (
    ConfirmSerializer,
    PaymentCreateSerializer,
    PaymentDetailSerializer,
    PaymentSerializer,
    RescheduleSerializer,
    ResolveSerializer,
)
from apps.payments.idempotency import IdempotencyMixin
from apps.payments.selectors.payment_detail_selector import (
    PaymentDetailSelector,
)
from apps.payments.services.confirm_service import PaymentConfirmService
from apps.payments.services.payment_create_service import PaymentCreateService
from apps.teams.access import AccountScopedMixin, RequiresCapability
from apps.teams.permissions import SEND_MONEY
from apps.payments.services.resolution_service import (
    PaymentResolutionService,
)
from rest_framework.exceptions import ValidationError

from apps.payments.api.serializers.responses import (
    BatchCancelEnvelope,
    BatchConfirmEnvelope,
    BatchStatusEnvelope,
    PaymentCreateEnvelope,
    PaymentEnvelope,
    PaymentStatusEnvelope,
    envelope,
)
from apps.payments.api.serializers.resolution import (
    PaymentFailureResponseSerializer,
    ResolveResponseSerializer,
)
from apps.common.error_codes import RECEIPT_NOT_READY
from apps.common.exceptions import NotFoundException

PaymentDetailEnvelope = envelope(
    "PaymentDetailEnvelope", PaymentDetailSerializer()
)
CONFLICT_RESPONSE = OpenApiResponse(
    description="The cancellation window has closed (confirmed payments only)."
)


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
    responses={201: PaymentCreateEnvelope},
)
class PaymentCreateAPIView(AccountScopedMixin, IdempotencyMixin, BaseAPIView):

    service_class = PaymentCreateService
    idempotency_endpoint = "payments.create"

    def post(self, request):
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def handler():
            result = self.service.create(
                user=self.account(request),
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
    responses={200: BatchConfirmEnvelope},
)
class BatchConfirmAPIView(AccountScopedMixin, IdempotencyMixin, BaseAPIView):

    service_class = PaymentConfirmService
    idempotency_endpoint = "payments.confirm_batch"
    permission_classes = BaseAPIView.permission_classes + [RequiresCapability]
    required_capability = SEND_MONEY

    def post(self, request, batch_id):
        serializer = ConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def handler():
            result = self.service.confirm_batch(
                user=self.account(request),
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
    responses={200: PaymentEnvelope},
)
class PaymentConfirmAPIView(AccountScopedMixin, IdempotencyMixin, BaseAPIView):

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
                user=self.account(request),
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
    responses={200: PaymentStatusEnvelope},
)
class PaymentStatusAPIView(AccountScopedMixin, BaseAPIView):

    def get(self, request, payment_id):
        selector = PaymentDetailSelector()
        payment = selector.get_payment(self.account(request), payment_id)

        if payment is None:
            raise NotFoundException("Payment not found.")

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
    responses={200: BatchStatusEnvelope},
)
class BatchStatusAPIView(AccountScopedMixin, BaseAPIView):

    def get(self, request, batch_id):
        selector = PaymentDetailSelector()
        batch = selector.get_batch(self.account(request), batch_id)

        if batch is None:
            raise NotFoundException("Batch not found.")

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
    responses={200: PaymentDetailEnvelope},
)
class PaymentDetailAPIView(AccountScopedMixin, BaseAPIView):

    def get(self, request, payment_id):
        payment = PaymentDetailSelector().get_payment(
            self.account(request), payment_id
        )

        if payment is None:
            raise NotFoundException("Payment not found.")

        return ApiResponse.success(
            data=PaymentDetailSerializer(payment).data,
            message="Payment fetched successfully.",
        )

    @extend_schema(
        tags=["Payments"],
        summary="Reschedule an unconfirmed payment",
        description=(
            "Changes scheduled_for in place (null = pay now) and recomputes "
            "the start, arrival and cancellation dates. Only before confirm; "
            "a confirmed payment needs cancel and a new payment. Answers with "
            "the payment detail."
        ),
        request=RescheduleSerializer,
        responses={200: PaymentDetailEnvelope},
    )
    def patch(self, request, payment_id):
        serializer = RescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        PaymentCreateService().reschedule(
            user=self.account(request),
            payment_id=payment_id,
            scheduled_for=serializer.validated_data["scheduled_for"],
        )

        payment = PaymentDetailSelector().get_payment(
            self.account(request), payment_id
        )

        return ApiResponse.success(
            data=PaymentDetailSerializer(payment).data,
            message="Payment rescheduled.",
        )


@extend_schema(
    tags=["Payments"],
    summary="Cancel a payment",
    description="Allowed until the cancellation deadline; 409 afterwards.",
    request=None,
    responses={200: PaymentEnvelope, 409: CONFLICT_RESPONSE},
)
class PaymentCancelAPIView(AccountScopedMixin, BaseAPIView):

    service_class = PaymentConfirmService

    def post(self, request, payment_id):
        payment = self.service.cancel_payment(
            user=self.account(request), payment_id=payment_id
        )

        return ApiResponse.success(
            data=PaymentSerializer(payment).data,
            message="Payment cancelled.",
        )


@extend_schema(
    tags=["Payments"],
    summary="Cancel a batch",
    request=None,
    responses={200: BatchCancelEnvelope, 409: CONFLICT_RESPONSE},
)
class BatchCancelAPIView(AccountScopedMixin, BaseAPIView):

    service_class = PaymentConfirmService

    def post(self, request, batch_id):
        result = self.service.cancel_batch(
            user=self.account(request), batch_id=batch_id
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
        "Display-ready title and explanation, the reason code and the "
        "balance at the attempt, days overdue, the vendor's late-fee "
        "countdown and the actions resolve accepts."
    ),
    responses={200: PaymentFailureResponseSerializer},
)
class PaymentFailureAPIView(AccountScopedMixin, BaseAPIView):

    service_class = PaymentResolutionService

    def get(self, request, payment_id):
        return ApiResponse.success(
            data=self.service.failure(
                user=self.account(request), payment_id=payment_id
            ),
            message="Failure detail fetched successfully.",
        )


@extend_schema(
    tags=["Payments"],
    summary="Resolve a failed payment",
    description=(
        "retry, change_method or reschedule (lowercase). Always creates a "
        "new payment against the same bill; the failed one stays terminal. "
        "The new payment needs confirming: show authorization_text, then "
        "POST payments/<id>/confirm with it. change_method moves to the new "
        "method's rail."
    ),
    request=ResolveSerializer,
    responses={201: ResolveResponseSerializer},
)
class PaymentResolveAPIView(AccountScopedMixin, IdempotencyMixin, BaseAPIView):

    service_class = PaymentResolutionService
    idempotency_endpoint = "payments.resolve"

    def post(self, request, payment_id):
        serializer = ResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def handler():
            result = self.service.resolve(
                user=self.account(request),
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
                    # The replacement needs confirming like any new payment
                    # (PAY-6): show this, then POST payments/<id>/confirm.
                    "authorization_text": result["authorization_text"],
                    "requires_confirmation": True,
                },
                message=f"Payment {result['action']} scheduled.",
                status_code=status.HTTP_201_CREATED,
            )

        return self.run_idempotent(request, handler)


@extend_schema(
    tags=["Payments"],
    summary="Receipt PDF",
    description=(
        "A completed payment's receipt as a PDF download: reference, payee, "
        "date, account, method, amount, fee and total. 409 until the payment "
        "has completed."
    ),
    responses={(200, "application/pdf"): bytes},
)
class PaymentReceiptPDFAPIView(AccountScopedMixin, BaseAPIView):

    def get(self, request, payment_id):
        from apps.common.exceptions import ConflictException
        from apps.payments.services.receipt_pdf import render_receipt

        payment = PaymentDetailSelector().get_payment(
            self.account(request), payment_id
        )

        if payment is None:
            raise NotFoundException("Payment not found.")

        if payment.status != PaymentStatus.SUCCESSFUL:
            raise ConflictException(
                "A receipt is available once the payment has completed.",
                code=RECEIPT_NOT_READY,
            )

        return render_receipt(payment)
