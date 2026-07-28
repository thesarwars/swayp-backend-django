

from django.contrib import admin
from django.urls import path,include

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

urlpatterns = [
    path("admin/", admin.site.urls),

      path(
        "api/schema/",
        SpectacularAPIView.as_view(),
        name="schema",
    ),

    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(
            url_name="schema"
        ),
        name="swagger-ui",
    ),

    path(
        "api/redoc/",
        SpectacularRedocView.as_view(
            url_name="schema"
        ),
        name="redoc",
    ),
    path("api/v1/", include("api.v1.urls")),
    # Versionless: a processor-registered URL must never move with an
    # API version (E6-S8).
    path("webhooks/", include("apps.webhooks.api.urls")),
]
