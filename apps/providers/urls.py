from django.urls import path

from .views import ProviderListAPIView

# ``search/`` is gone (E3-S7, E6-S10). It was a thin wrapper around the same
# ProviderService.list_providers(search=...) that ``providers/?search=``
# already exposes, and the biller directory it stood in for is now
# ``vendors/directory-search/``. Two epics and the dashboard plan all called
# it superseded; nothing referenced it in a test or a client-facing doc.
urlpatterns = [
    path(
        "",
        ProviderListAPIView.as_view(),
        name="provider-list",
    ),
]
