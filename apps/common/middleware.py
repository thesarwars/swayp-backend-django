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
