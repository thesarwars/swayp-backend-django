from django.urls import include, path

urlpatterns = [
    path(
        "auth/",
        include("apps.authentication.api.urls"),
    ),

    path(
        "bill-categories/",
        include("apps.bill_categories.urls"),
    ),
    path(
        "banking/",
        include("apps.banking.api.urls"),
    ),
    path(
        "bills/",
        include("apps.bills.urls"),
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
        include("apps.payments.api.urls"),
        
    ),
    path(
        "vendors/",include("apps.vendors.urls")
    ),
    path(
        "ai/",
        include("apps.ai_advisor.api.urls"),
    ),
]