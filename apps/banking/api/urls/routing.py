from django.urls import path

from apps.banking.api.views.routing import RoutingValidateAPIView

urlpatterns = [
    path(
        "routing/validate/",
        RoutingValidateAPIView.as_view(),
        name="routing-validate",
    ),
]
