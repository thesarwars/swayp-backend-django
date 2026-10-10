from rest_framework.views import exception_handler

from .responses import ApiResponse


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        return ApiResponse.error(
            message="Internal server error.",
            status_code=500,
        )

    if isinstance(response.data, dict):

        if "detail" not in response.data:
            built = ApiResponse.error(
                message="Validation failed.",
                errors=response.data,
                status_code=response.status_code,
            )
        else:
            built = ApiResponse.error(
                message=_flatten_detail(response.data["detail"]),
                status_code=response.status_code,
            )

        return _carry_retry_after(built, exc, original=response)

    return _carry_retry_after(response, exc)


def _flatten_detail(detail):
    """Render a detail as a plain sentence.

    A ValidationError raised as ``{"detail": "..."}`` arrives here wrapped in a
    list, which str() would render as "[ErrorDetail(string='...')]" — leaking
    DRF internals into a user-facing message.
    """
    if isinstance(detail, (list, tuple)):
        return " ".join(str(item) for item in detail) if detail else ""

    return str(detail)


def _carry_retry_after(response, exc, original=None):
    """Preserve Retry-After, which rebuilding the body would otherwise drop.

    Two sources: our own throttles set ``exc.retry_after``, and DRF's built-in
    throttling (ScopedRateThrottle and friends) puts the header on the
    response it builds. Only the first used to survive, so every DRF-throttled
    429 (routing validation, the AI cash context) arrived with "available in
    60 seconds" in the text and no header to act on (VEND-10).
    """
    retry_after = getattr(exc, "retry_after", None)

    if not retry_after and original is not None:
        retry_after = original.get("Retry-After")

    if retry_after:
        response["Retry-After"] = str(retry_after)

    return response