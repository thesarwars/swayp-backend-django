from drf_spectacular.utils import extend_schema

from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)

from .serializers import (
    PaymentHistoryQuerySerializer,
    PaymentHistoryResponseSerializer,
    CreatePaymentResponseSerializer,
    CreatePaymentSerializer,
)


payment_history_schema = extend_schema(
    tags=["Payments"],
    summary="Payment History",
    description="Returns payment history of the authenticated user.",
    parameters=[
        PaymentHistoryQuerySerializer,
    ],
    responses={
        200: PaymentHistoryResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)


create_payment_schema = extend_schema(
    tags=["Payments"],
    summary="Create Payment",
    description="Creates a new bill payment.",
    request=CreatePaymentSerializer,
    responses={
        201: CreatePaymentResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)