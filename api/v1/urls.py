from django.urls import include, path

urlpatterns = [
    path(
        "auth/",
        include("apps.authentication.api.urls"),
    ),

    path("wallet/", include("apps.wallet.urls")),

    path(
        "bill-categories/",
        include("apps.bill_categories.urls"),
    ),
    path(
        "providers/",
        include("apps.providers.urls"),
    ),

    
    path(
        "notifications/",
        include("apps.notifications.urls"),
    ),

    path(
        "dashboard/",
        include("apps.dashboard.urls"),
    ),

      path(
        "payments/",
        include("apps.payments.urls"),
    ),
]