"""Liveness and readiness (deployment).

Two different questions, deliberately split. A load balancer asking "is this
process alive" must not be told no because Redis is briefly unreachable —
restarting a healthy web process does not fix a broken broker, and cycling
every container during a Redis blip turns a degraded service into an outage.

- ``/healthz``  liveness  — the process is up. Never touches a dependency.
- ``/readyz``   readiness — it can actually serve. Checks the database.

Both are unauthenticated: a probe has no token, and neither reveals anything
beyond whether the service works.
"""

from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView


@extend_schema(exclude=True)
class LivenessAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"status": "ok"})


@extend_schema(exclude=True)
class ReadinessAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            # No detail in the body: a probe endpoint is unauthenticated, and
            # a database error message is not something to hand to the world.
            return Response(
                {"status": "unavailable", "database": False},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"status": "ok", "database": True})
