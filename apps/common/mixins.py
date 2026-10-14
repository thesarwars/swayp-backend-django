from rest_framework.permissions import AllowAny, IsAuthenticated


class AuthenticatedAPIViewMixin:
    """
    Default authentication for internal APIs.
    Override in a view if needed.
    """

    permission_classes = [IsAuthenticated]


class PublicAPIViewMixin:
    """
    Unauthenticated entry points (register, login, password reset).

    authentication_classes is emptied as well as opening permissions: leaving
    JWT authentication on would reject a request carrying a stale token before
    the view ever ran, which is wrong for endpoints meant to be reachable
    without one.
    """

    permission_classes = [AllowAny]
    authentication_classes = []


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

class EnvelopeResponseMixin:
    """Wraps a generic view's success answer in {success, message, data}
    (web C1).

    The vendor endpoints are DRF generic views and answered bare: a list as
    {items, pagination} and an object as itself, while every other module
    answers through ApiResponse. A list becomes data = the items with
    pagination beside it, exactly as ApiResponse sends a paged list. Errors
    already go through the exception handler and are left alone.
    """

    success_message = "Success"

    def finalize_response(self, request, response, *args, **kwargs):
        data = getattr(response, "data", None)

        if (
            200 <= response.status_code < 300
            and isinstance(data, (dict, list))
            and not (isinstance(data, dict) and "success" in data)
        ):
            from apps.common.casing import with_snake_case

            if isinstance(data, dict) and set(data) == {"items", "pagination"}:
                response.data = {
                    "success": True,
                    "message": self.success_message,
                    "data": data["items"],
                    "pagination": with_snake_case(data["pagination"]),
                }
            else:
                response.data = {
                    "success": True,
                    "message": self.success_message,
                    "data": data,
                }

        return super().finalize_response(request, response, *args, **kwargs)
