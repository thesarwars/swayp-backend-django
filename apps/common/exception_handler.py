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
            return ApiResponse.error(
                message="Validation failed.",
                errors=response.data,
                status_code=response.status_code,
            )

        
        return ApiResponse.error(
            message=str(response.data["detail"]),
            status_code=response.status_code,
        )

    return response