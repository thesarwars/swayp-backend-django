from django.urls import path

from apps.authentication.api.views.google_login import GoogleLoginView

urlpatterns = [
    path("/login/google", GoogleLoginView.as_view(), name="login-google"),
]
