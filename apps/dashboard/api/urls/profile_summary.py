from django.urls import path

from apps.dashboard.api.views.profile_summary import ProfileSummaryAPIView

urlpatterns = [
    path(
        "/profile-summary",
        ProfileSummaryAPIView.as_view(),
        name="dashboard-profile-summary",
    ),
]
