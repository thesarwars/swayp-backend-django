from rest_framework.permissions import IsAuthenticated


class AuthenticatedAPIViewMixin:
    """
    Default authentication for internal APIs.
    Override in a view if needed.
    """

    permission_classes = [IsAuthenticated]


class ServiceMixin:
    """
    Lazily instantiate the configured service class.
    """

    service_class = None

    @property
    def service(self):
        if self.service_class is None:
            raise NotImplementedError(
                "service_class must be defined."
            )

        if not hasattr(self, "_service"):
            self._service = self.service_class()

        return self._service