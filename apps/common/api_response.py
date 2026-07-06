from rest_framework.response import Response
from rest_framework import status


def success_response(
    data=None,
    message="Success",
    pagination=None,
    status_code=status.HTTP_200_OK,
):
    response = {
        "success": True,
        "message": message,
        "data": data,
    }

    if pagination is not None:
        response["pagination"] = pagination

    return Response(response, status=status_code)


def error_response(
    message="Something went wrong",
    errors=None,
    status_code=status.HTTP_400_BAD_REQUEST,
):
    response = {
        "success": False,
        "message": message,
    }

    if errors is not None:
        response["errors"] = errors

    return Response(response, status=status_code)