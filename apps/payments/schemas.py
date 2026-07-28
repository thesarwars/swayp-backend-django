from drf_spectacular.utils import extend_schema

from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    NOT_FOUND_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)

from drf_spectacular.utils import extend_schema

from .serializers import (
    PaymentStatusUpdateResponseSerializer,
)
from .serializers import (
    PaymentStatusUpdateResponseSerializer,
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


payment_success_schema = extend_schema(
    deprecated=True,
    tags=["Payments"],
    summary="Mark Payment Successful",
    description="Marks a payment as successful.",
    responses={
        200: PaymentStatusUpdateResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
    },
)




payment_processing_schema = extend_schema(
    deprecated=True,
    tags=["Payments"],
    summary="Mark Payment Processing",
    description="Marks a payment as processing.",
    responses={
        200: PaymentStatusUpdateResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
    },
)

payment_failed_schema = extend_schema(
    deprecated=True,
    tags=["Payments"],
    summary="Mark Payment Failed",
    description="Marks a payment as failed. Staff only.",
    responses={
        200: PaymentStatusUpdateResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
    },
)