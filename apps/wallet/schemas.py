from drf_spectacular.utils import extend_schema

from apps.common.swagger import (
    UNAUTHORIZED_RESPONSE,
)

from .serializers import WalletSummaryResponseSerializer


wallet_summary_schema = extend_schema(
    tags=["Wallet"],
    summary="Wallet Summary",
    description="""
Returns the authenticated user's wallet summary.
""",
    responses={
        200: WalletSummaryResponseSerializer,
        401: UNAUTHORIZED_RESPONSE,
    },
)