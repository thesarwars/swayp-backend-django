from rest_framework.views import APIView

from .mixins import (
    AuthenticatedAPIViewMixin,
    ServiceMixin,
)


class BaseAPIView(AuthenticatedAPIViewMixin,ServiceMixin,APIView):
    """
    Base view for authenticated APIs.

    Provides:
        • authentication
        • lazy service creation
    """

    pass