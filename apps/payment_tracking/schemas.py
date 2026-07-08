from drf_spectacular.utils import extend_schema

from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)

from .serializers import (
    PaymentTrackingQuerySerializer,
    PaymentTrackingResponseSerializer,
)


payment_tracking_schema = extend_schema(
    tags=["Payment Tracking"],
    summary="Payment Tracking",
    description="Returns ongoing payment tracking history for the authenticated user.",
    parameters=[
        PaymentTrackingQuerySerializer,
    ],
    responses={
        200: PaymentTrackingResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)