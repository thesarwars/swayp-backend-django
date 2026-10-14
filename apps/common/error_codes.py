"""The ``code`` on every error body (API-3).

A client branches on ``code``, never on ``message``: the message is copy and
gets reworded. Every error carries one. A raise site that the client must
tell apart passes a specific code from SPECIFIC; anything else falls back to
the generic code for its status.

Add to SPECIFIC, never rename: a code is a contract.
"""

#: By status, when the raise site named nothing more specific.
BY_STATUS = {
    400: "validation_failed",
    401: "not_authenticated",
    402: "plan_limit",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    409: "conflict",
    415: "unsupported_media_type",
    422: "unprocessable",
    429: "throttled",
    500: "server_error",
    503: "service_unavailable",
}

# Codes a raise site passes (``code=...``) so the client can branch.
NO_FUNDING_ACCOUNT = "no_funding_account"
#: The *payee* has no saved payment method, as opposed to the payer having
#: no bank: there is nowhere to send the money. Every bill the bank scan
#: imports starts in this state, so the client branches on it to offer
#: adding the provider's details.
NO_PAYEE_METHOD = "no_payee_method"
IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"
IDEMPOTENCY_IN_PROGRESS = "idempotency_in_progress"
RECEIPT_NOT_READY = "receipt_not_ready"
NOT_CANCELLABLE = "not_cancellable"
CANCEL_WINDOW_CLOSED = "cancel_window_closed"
# Sign-in, verification and billing refusals (web C8, AUTH-3).
INVALID_CREDENTIALS = "invalid_credentials"
ACCOUNT_LOCKED = "account_locked"
ACCOUNT_INACTIVE = "account_inactive"
ACCOUNT_NOT_VERIFIED = "account_not_verified"
OTP_INVALID = "otp_invalid"
OTP_EXPIRED = "otp_expired"
OTP_NOT_PENDING = "otp_not_pending"
OTP_ATTEMPTS_EXCEEDED = "otp_attempts_exceeded"
RESET_TOKEN_INVALID = "reset_token_invalid"
EMAIL_TAKEN = "email_taken"
PHONE_TAKEN = "phone_taken"
ALREADY_SUBSCRIBED = "already_subscribed"
CARD_DECLINED = "card_declined"
# Webhooks (web C6): for the provider's delivery log, not for an app.
INVALID_SIGNATURE = "invalid_signature"
MALFORMED_PAYLOAD = "malformed_payload"

SPECIFIC = {
    NO_FUNDING_ACCOUNT,
    NO_PAYEE_METHOD,
    IDEMPOTENCY_KEY_REUSED,
    IDEMPOTENCY_IN_PROGRESS,
    RECEIPT_NOT_READY,
    NOT_CANCELLABLE,
    CANCEL_WINDOW_CLOSED,
    INVALID_SIGNATURE,
    MALFORMED_PAYLOAD,
    INVALID_CREDENTIALS,
    ACCOUNT_LOCKED,
    ACCOUNT_INACTIVE,
    ACCOUNT_NOT_VERIFIED,
    OTP_INVALID,
    OTP_EXPIRED,
    OTP_NOT_PENDING,
    OTP_ATTEMPTS_EXCEEDED,
    RESET_TOKEN_INVALID,
    EMAIL_TAKEN,
    PHONE_TAKEN,
    ALREADY_SUBSCRIBED,
    CARD_DECLINED,
    # Already the default_code of their exceptions.
    "plan_limit",
    "role_forbidden",
    "otp_throttled",
    "channel_not_available",
    "google_unavailable",
    # simplejwt: the access token is expired or bad, so refresh.
    "token_not_valid",
}


def code_for(status_code):
    return BY_STATUS.get(status_code, "error")
