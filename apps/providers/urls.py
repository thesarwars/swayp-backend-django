from django.urls import path

from .views import ProviderListAPIView

urlpatterns = [
    path(
        "",
        ProviderListAPIView.as_view(),
        name="provider-list",
    ),
]