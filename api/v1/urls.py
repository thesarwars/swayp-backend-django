from django.urls import include, path

urlpatterns = [
    path(
        "/auth",
        include("apps.authentication.api.urls"),
    ),

    path(
        "/bill-categories",
        include("apps.bill_categories.urls"),
    ),
    path(
        "/billing",
        include("apps.billing.api.urls"),
    ),
    path(
        "/banking",
        include("apps.banking.api.urls"),
    ),
    path(
        "/bills",
        include("apps.bills.urls"),
    ),
    path(
        "/providers",
        include("apps.providers.urls"),
    ),

    
    path(
        "/notifications",
        include("apps.notifications.api.urls"),
    ),

    path(
        "/dashboard",
        include("apps.dashboard.api.urls"),
    ),

    path(
        "/payments",
        include("apps.payments.api.urls"),
        
    ),
    path(
        "/vendors",include("apps.vendors.urls")
    ),
    path(
        "/ai",
        include("apps.ai_advisor.api.urls"),
    ),
    path(
        "/reports",
        include("apps.reports.api.urls"),
    ),
    path(
        "/teams",
        include("apps.teams.api.urls"),
    ),
    path(
        "/users",
        include("apps.users.api.urls"),
    ),
]