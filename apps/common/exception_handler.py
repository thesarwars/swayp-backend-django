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

        return _carry_retry_after(built, exc)

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


def _carry_retry_after(response, exc):
    """Preserve Retry-After, which rebuilding the body would otherwise drop."""
    retry_after = getattr(exc, "retry_after", None)

    if retry_after:
        response["Retry-After"] = str(retry_after)

    return response