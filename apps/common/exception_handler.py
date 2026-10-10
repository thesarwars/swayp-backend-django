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
                errors=_as_lists(response.data),
                status_code=response.status_code,
            )
        else:
            built = ApiResponse.error(
                message=_flatten_detail(response.data["detail"]),
                status_code=response.status_code,
            )

        _add_codes(built, exc, context)

        return _carry_retry_after(built, exc, original=response)

    return _carry_retry_after(response, exc)


def _as_lists(errors):
    """Every field's errors as a list of strings (API-4).

    A serializer reports ``{"field": ["..."]}``, but a service raising
    ``ValidationError({"field": "..."})`` reported a bare string, so a
    client had to accept both. Nested fields keep their nesting; only the
    leaves change.
    """
    if isinstance(errors, dict):
        return {key: _as_lists(value) for key, value in errors.items()}

    if isinstance(errors, (list, tuple)):
        if any(isinstance(item, (dict, list, tuple)) for item in errors):
            # A list of per-item errors (many=True): keep the positions.
            return [_as_lists(item) for item in errors]

        return [str(item) for item in errors]

    return [str(errors)]


def _add_codes(response, exc, context):
    """Machine-readable codes on 402 and on a role's 403 (BILLING-11).

    402: ``{code: "plan_limit", limit: "BANKS"|"SEATS"|"CHECKS"|null}``.
    403 from RequiresCapability: ``{code: "role_forbidden", capability}``.
    """
    from apps.common.exceptions import PlanLimitExceededException
    from apps.teams.access import ROLE_FORBIDDEN_CODE

    if isinstance(exc, PlanLimitExceededException):
        response.data["code"] = exc.body_code
        response.data["limit"] = exc.limit
        return

    if response.status_code == 403 and _code_of(exc) == ROLE_FORBIDDEN_CODE:
        view = context.get("view") if context else None
        response.data["code"] = ROLE_FORBIDDEN_CODE
        response.data["capability"] = getattr(
            view, "required_capability", None
        )


def _code_of(exc):
    try:
        codes = exc.get_codes()
    except AttributeError:
        return None

    return codes if isinstance(codes, str) else None


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