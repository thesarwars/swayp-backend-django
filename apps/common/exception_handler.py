from rest_framework.views import exception_handler

from .error_codes import SPECIFIC, code_for
from .responses import ApiResponse


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        built = ApiResponse.error(
            message="Internal server error.",
            status_code=500,
        )
        built.data["code"] = code_for(500)

        return built

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

    else:
        # ValidationError(["..."]) has no field to hang the message on; it
        # used to reach the client as a bare JSON list, outside the envelope.
        built = ApiResponse.error(
            message=_flatten_detail(response.data),
            status_code=response.status_code,
        )

    _add_codes(built, exc, context)

    return _carry_retry_after(built, exc, original=response)


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
    """A ``code`` on every error (API-3), and its companions.

    The first specific code named anywhere in the exception wins (see
    apps/common/error_codes.py); otherwise the generic code for the status.
    402 also carries ``limit`` and a role's 403 ``capability`` (BILLING-11).
    """
    from apps.common.exceptions import PlanLimitExceededException
    from apps.teams.access import ROLE_FORBIDDEN_CODE

    if isinstance(exc, PlanLimitExceededException):
        response.data["code"] = exc.body_code
        response.data["limit"] = exc.limit
        return

    specific = [c for c in _leaf_codes(exc) if c in SPECIFIC]
    code = specific[0] if specific else code_for(response.status_code)
    response.data["code"] = code

    if code == ROLE_FORBIDDEN_CODE:
        view = context.get("view") if context else None
        response.data["capability"] = getattr(
            view, "required_capability", None
        )


def _leaf_codes(exc):
    try:
        codes = exc.get_codes()
    except AttributeError:
        return []

    leaves = []

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
        else:
            leaves.append(str(node))

    walk(codes)

    return leaves


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