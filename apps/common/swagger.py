from drf_spectacular.utils import OpenApiResponse

BAD_REQUEST_RESPONSE = OpenApiResponse(
    description="Bad Request"
)

UNAUTHORIZED_RESPONSE = OpenApiResponse(
    description="Unauthorized"
)

FORBIDDEN_RESPONSE = OpenApiResponse(
    description="Forbidden"
)

NOT_FOUND_RESPONSE = OpenApiResponse(
    description="Not Found"
)

SERVER_ERROR_RESPONSE = OpenApiResponse(
    description="Internal Server Error"
)