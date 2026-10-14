"""JSON for every API error, including the ones DRF never sees (API-4).

An unknown route, a trailing slash or an uncaught crash under /api/ used to
answer Django's HTML page, so a client parsing the envelope got a syntax
error instead of a message. DRF's own errors are already JSON and pass
through untouched.
"""

from django.http import JsonResponse

from apps.common.error_codes import code_for

API_PREFIX = "/api/"

MESSAGES = {
    404: "Not found.",
    405: "Method not allowed.",
    500: "Internal server error.",
}


class JsonApiErrorMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if (
            response.status_code >= 400
            and request.path.startswith(API_PREFIX)
            and not response.get("Content-Type", "").startswith(
                "application/json"
            )
        ):
            return JsonResponse(
                {
                    "success": False,
                    "message": MESSAGES.get(
                        response.status_code, "Request failed."
                    ),
                    "code": code_for(response.status_code),
                },
                status=response.status_code,
            )

        return response


class StripTrailingSlashMiddleware:
    """``/api/v1/billing/fees/`` routes like ``/api/v1/billing/fees`` (API-6).

    Routes are declared without a trailing slash, and the docs wrote many
    with one, so following the docs gave a 404. The path is rewritten in
    place rather than redirected: a redirect would turn a POST into a GET in
    some clients and drop its body.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info

        if path.startswith(API_PREFIX) and len(path) > len(API_PREFIX):
            stripped = path.rstrip("/")

            if stripped != path:
                request.path_info = stripped
                request.path = request.path.rstrip("/")

        return self.get_response(request)


#: Spellings of one query parameter across the API (web C3). Endpoints grew
#: different names for the same thing: payments/history reads fromDate,
#: reports and bills/occurrences date_from, billing/fees from_date;
#: providers and payment history categoryId, the rest category. Whichever
#: spelling a request uses, every spelling in its group is filled in, so each
#: endpoint finds the name it reads. The documented, preferred one is first.
QUERY_ALIASES = (
    ("page_size", "pageSize"),
    ("date_from", "from_date", "fromDate"),
    ("date_to", "to_date", "toDate"),
    ("category", "category_id", "categoryId"),
)


class QueryAliasMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(API_PREFIX) and request.GET:
            query = None

            for group in QUERY_ALIASES:
                sent = next((name for name in group if name in request.GET), None)

                if sent is None:
                    continue

                values = request.GET.getlist(sent)

                for name in group:
                    if name not in request.GET:
                        if query is None:
                            query = request.GET.copy()
                        query.setlist(name, values)

            if query is not None:
                request.GET = query

        return self.get_response(request)


class CamelCaseDeprecationMiddleware:
    """Deprecation and Sunset headers on every API answer that still
    carries camelCase copies (web C2), so a client sees what to move before
    15 Nov 2026 instead of finding out when the keys vanish."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from apps.common.casing import (
            has_camel_case_keys,
            mark_camel_case_deprecated,
        )

        response = self.get_response(request)

        if request.path.startswith(API_PREFIX) and has_camel_case_keys(
            getattr(response, "data", None)
        ):
            mark_camel_case_deprecated(response)

        return response
