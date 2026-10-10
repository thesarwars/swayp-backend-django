from rest_framework import status
from rest_framework.response import Response

from apps.common.casing import with_snake_case
from apps.common.error_codes import code_for


class ApiResponse:

    @staticmethod
    def success(
        *,
        data=None,
        message="Success",
        pagination=None,
        extra=None,
        status_code=status.HTTP_200_OK,
    ):
        body = {
            "success": True,
            "message": message,
            "data": data,
        }

        if pagination:
            body["pagination"] = with_snake_case(pagination)

        # Top-level keys that describe the whole list rather than one item,
        # beside pagination (e.g. unreadCount on GET notifications).
        if extra:
            body.update(with_snake_case(extra))

        return Response(body, status=status_code)

    @staticmethod
    def error(
        *,
        message,
        errors=None,
        status_code=status.HTTP_400_BAD_REQUEST,
        code=None,
    ):
        body = {
            "success": False,
            "message": message,
            # Every error carries a code (API-3), including the few built
            # here directly rather than raised. The exception handler
            # replaces it with a more specific one when it has one.
            "code": code or code_for(status_code),
        }

        if errors:
            body["errors"] = errors

        return Response(body, status=status_code)