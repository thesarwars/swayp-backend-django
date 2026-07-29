from django.urls import path

from apps.dashboard.api.views.home import HomeAPIView

urlpatterns = [
    path(
        "home/",
        HomeAPIView.as_view(),
        name="dashboard-home",
    ),
]
