from drf_spectacular.utils import extend_schema

from apps.common.swagger import (
    UNAUTHORIZED_RESPONSE,
)

from .serializers import (
    BillCategoryListResponseSerializer,
)


bill_category_list_schema = extend_schema(
    tags=["Bill Categories"],
    summary="List Bill Categories",
    description="Returns all active bill categories.",
    responses={
        200: BillCategoryListResponseSerializer,
        401: UNAUTHORIZED_RESPONSE,
    },
)