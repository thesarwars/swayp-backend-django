from drf_spectacular.utils import extend_schema

from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)

from .serializers import (
    ProfileSummaryResponseSerializer,
)


profile_summary_schema = extend_schema(
    tags=["Dashboard"],
    summary="Profile Summary",
    description=(
        "Returns the authenticated user's profile summary "
        "for the dashboard."
    ),
    responses={
        200: ProfileSummaryResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)