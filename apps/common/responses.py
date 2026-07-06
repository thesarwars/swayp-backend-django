from rest_framework.response import Response
from rest_framework import status


class ApiResponse:

    @staticmethod
    def success(
        *,
        data=None,
        message="Success",
        pagination=None,
        status_code=status.HTTP_200_OK,
    ):
        body = {
            "success": True,
            "message": message,
            "data": data,
        }

        if pagination:
            body["pagination"] = pagination

        return Response(body, status=status_code)

    @staticmethod
    def error(
        *,
        message,
        errors=None,
        status_code=status.HTTP_400_BAD_REQUEST,
    ):
        body = {
            "success": False,
            "message": message,
        }

        if errors:
            body["errors"] = errors

        return Response(body, status=status_code)