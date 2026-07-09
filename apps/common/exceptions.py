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

class InsufficientBalanceException(BadRequestException):

    default_detail = "Insufficient wallet balance."
    default_code = "insufficient_balance"


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


class WalletFrozenException(
    BadRequestException
):
    default_message = (
        "Wallet is frozen."
    )