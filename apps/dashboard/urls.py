from django.urls import path

from .views import ProfileSummaryAPIView


urlpatterns = [
    path(
        "profile-summary/",
        ProfileSummaryAPIView.as_view(),
        name="dashboard-profile-summary",
    ),
]