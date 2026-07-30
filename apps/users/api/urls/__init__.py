from django.urls import path

from apps.users.api.views.profile import ProfileAPIView

urlpatterns = [
    path("profile/", ProfileAPIView.as_view(), name="user-profile"),
]
