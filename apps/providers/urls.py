from django.urls import path

from .views import ProviderListAPIView, ProviderSearchAPIView

urlpatterns = [
    path(
        "",
        ProviderListAPIView.as_view(),
        name="provider-list",
    ),

     path(
        "search/",
        ProviderSearchAPIView.as_view(),
        name="provider-search",
    ),
]