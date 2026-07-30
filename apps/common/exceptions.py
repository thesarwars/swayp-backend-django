from rest_framework.exceptions import APIException
from rest_framework import status


class BadRequestException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Bad request."
    default_code = "bad_request"


class NotFoundException(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Resource not found."
    default_code = "not_found"


class ConflictException(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Resource already exists."
    default_code = "conflict"


class ForbiddenException(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Permission denied."
    default_code = "forbidden"


class UnprocessableEntityException(APIException):
    """Well-formed request that asks for something nonsensical (422).

    E.g. a balance projection for a date in the past (E7-S3).
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "The request could not be processed."
    default_code = "unprocessable_entity"


class ChannelNotAvailableException(APIException):
    """OTP delivery channel not available this release (E2-S1).

    SMS is deferred (BRD §1.2). 501 rather than 400 — the request is valid,
    the capability just isn't implemented yet.
    """

    status_code = status.HTTP_501_NOT_IMPLEMENTED
    default_detail = "This OTP delivery channel is not available in this release."
    default_code = "channel_not_available"


class ExportNotSupportedException(APIException):
    """Report export is not built yet (E8-S2).

    The output format — table vs CSV vs PDF, and which columns — is an open
    product question (PRD §10-Q4). Shipping a guessed CSV would create a
    contract clients then depend on, so the endpoint refuses.

    405 is what the epic pins. 501 would read better and
    ChannelNotAvailableException above is this codebase's precedent for it —
    but the epic says 405, so 405 it is. DRF sets no ``Allow`` header on this
    one, because it is not really a method problem.
    """

    status_code = status.HTTP_405_METHOD_NOT_ALLOWED
    default_detail = (
        "Report export is not supported yet. Read the JSON table from "
        "GET /api/v1/reports/ instead."
    )
    default_code = "export_not_supported"


class OTPThrottledException(APIException):
    """OTP resend rate limit (E2-S2). Carries a Retry-After header."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "Too many OTP requests. Please wait before retrying."
    default_code = "otp_throttled"

    def __init__(self, detail=None, retry_after=None):
        self.retry_after = retry_after

        if detail is None and retry_after:
            detail = (
                f"Too many OTP requests. Try again in {retry_after} seconds."
            )

        super().__init__(detail)

class InvalidPaymentStateException(BadRequestException):
    default_message = "Invalid payment state transition."

    def __init__(self, message=None):
        super().__init__(message or self.default_message)


class PaymentAlreadyRefundedException(
    InvalidPaymentStateException
):
    default_message = (
        "Payment has already been refunded."
    )


class PaymentAlreadyCompletedException(
    InvalidPaymentStateException
):
    default_message = (
        "Payment has already been completed."
    )


class PaymentAlreadyProcessingException(
    InvalidPaymentStateException
):
    default_message = (
        "Payment is already processing."
    )


class PaymentNotRefundableException(
    InvalidPaymentStateException
):
    default_message = (
        "Only successful payments can be refunded."
    )


class DuplicatePaymentException(
    BadRequestException
):
    default_message = (
        "Duplicate payment request."
    )


class ProviderUnavailableException(
    BadRequestException
):
    default_message = (
        "Payment provider is unavailable."
    )


class PlanLimitExceededException(APIException):
    """A plan ceiling would be breached (E9-S2).

    402 rather than 403: the request is authorised, it just needs a bigger
    plan. That distinction is what lets the client show an upgrade prompt
    instead of a permission error.
    """

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_detail = "This action exceeds your plan limit."
    default_code = "plan_limit_exceeded"

