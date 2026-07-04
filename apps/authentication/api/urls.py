from django.urls import path

from apps.authentication.api.views import RegisterView

urlpatterns = [
    path(
        "register/",
        RegisterView.as_view(),
        name="register",
    ),
]