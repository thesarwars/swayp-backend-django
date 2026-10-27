from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    name = "apps.authentication"

    def ready(self):
        # Registers the schema extension for SessionJWTAuthentication.
        from apps.authentication import schema  # noqa: F401
