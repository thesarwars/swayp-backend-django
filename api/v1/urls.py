from django.urls import include, path

urlpatterns = [
    path(
        "auth/",
        include("apps.authentication.api.urls"),
    ),

    path("wallet/", include("apps.wallet.urls")),
]