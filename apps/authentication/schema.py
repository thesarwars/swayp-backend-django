"""Publish SessionJWTAuthentication as the same bearer scheme simplejwt's
own class gets, so every authenticated route keeps its security block and
its 401 response."""

from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


class SessionJWTScheme(SimpleJWTScheme):
    target_class = "apps.authentication.authentication.SessionJWTAuthentication"
