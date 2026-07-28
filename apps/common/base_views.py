from rest_framework.views import APIView

from .mixins import (
    AuthenticatedAPIViewMixin,
    PublicAPIViewMixin,
    ServiceMixin,
)


class BaseAPIView(AuthenticatedAPIViewMixin, ServiceMixin, APIView):
    """
    Base view for authenticated APIs.

    Provides:
        • authentication
        • lazy service creation
    """

    pass


class PublicAPIView(PublicAPIViewMixin, ServiceMixin, APIView):
    """
    Base view for public APIs (E2-S5).

    Same lazy `service_class` wiring as BaseAPIView, but open to
    unauthenticated callers — auth endpoints are reachable without a token by
    definition.
    """

    pass
