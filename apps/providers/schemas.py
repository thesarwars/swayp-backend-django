from drf_spectacular.utils import extend_schema

from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)

from .serializers import (
    ProviderListResponseSerializer,
    ProviderQuerySerializer,
    ProviderSearchQuerySerializer,
)


provider_list_schema = extend_schema(
    tags=["Providers"],
    summary="List Providers",
    description="Returns providers with optional category filter and search.",
    parameters=[ProviderQuerySerializer],
    responses={
        200: ProviderListResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)

provider_search_schema = extend_schema(
    tags=["Providers"],
    summary="Search Providers",
    description="Search providers by keyword.",
    parameters=[ProviderSearchQuerySerializer],
    responses={
        200: ProviderListResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)