from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.common.exceptions import ConflictException
from apps.payments.idempotency import IdempotencyMixin
from apps.payments.models import IdempotencyKey

User = get_user_model()


class _CountingView(IdempotencyMixin, APIView):
    idempotency_endpoint = "test-create"
    calls = 0

    def post(self, request):
        def handler():
            type(self).calls += 1
            return Response(
                {"id": type(self).calls}, status=status.HTTP_201_CREATED
            )

        return self.run_idempotent(request, handler)


class IdempotencyMixinTests(TestCase):

    def setUp(self):
        _CountingView.calls = 0
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            email="idem@example.com",
            phone_number="+15125550001",
            password="Password@12345",
        )
        self.view = _CountingView.as_view()

    def _post(self, body, key=None):
        request = self.factory.post("/x/", body, format="json")
        if key:
            request.META["HTTP_IDEMPOTENCY_KEY"] = key
        force_authenticate(request, user=self.user)
        return self.view(request)

    def test_no_key_runs_normally(self):
        r1 = self._post({"a": 1})
        r2 = self._post({"a": 1})
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(_CountingView.calls, 2)  # ran twice, no dedupe

    def test_same_key_replays_without_rerunning(self):
        r1 = self._post({"a": 1}, key="k-1")
        r2 = self._post({"a": 1}, key="k-1")
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r1.data, r2.data)
        self.assertEqual(_CountingView.calls, 1)  # handler ran once
        self.assertEqual(IdempotencyKey.objects.count(), 1)
        self.assertEqual(
            IdempotencyKey.objects.get().state,
            IdempotencyKey.State.COMPLETED,
        )

    def test_same_key_different_body_conflicts(self):
        self._post({"a": 1}, key="k-2")
        # DRF turns the raised ConflictException into a 409 response.
        r = self._post({"a": 999}, key="k-2")
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(_CountingView.calls, 1)
