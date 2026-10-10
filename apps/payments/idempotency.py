"""Idempotency view mixin (E1-S7).

Wrap a money-creating handler so a repeated `Idempotency-Key` header replays the
first response instead of doing the work twice. Applied by E5 (bulk import) and
E6 (payment create/confirm/resolve).
"""

from __future__ import annotations

import hashlib
import json

from rest_framework.response import Response

from apps.common.error_codes import (
    IDEMPOTENCY_IN_PROGRESS,
    IDEMPOTENCY_KEY_REUSED,
)
from apps.common.exceptions import ConflictException
from apps.payments.models import IdempotencyKey

IDEMPOTENCY_HEADER = "Idempotency-Key"


def request_body_hash(data) -> str:
    payload = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def json_safe(data):
    """Coerce a response body into something JSONField can store.

    Response payloads routinely carry UUIDs, Decimals and dates, none of which
    are JSON-native. Without this the stored replay blows up at save time —
    turning a successful request into a 500.
    """
    return json.loads(json.dumps(data, default=str))


class IdempotencyMixin:
    """Adds `run_idempotent(request, handler)` to an APIView.

    `handler` is a zero-arg callable returning a DRF ``Response``. If the
    request carries no ``Idempotency-Key`` header, the handler runs normally.
    """

    def get_idempotency_endpoint(self, request) -> str:
        return getattr(self, "idempotency_endpoint", None) or request.path

    def run_idempotent(self, request, handler):
        key = request.headers.get(IDEMPOTENCY_HEADER)
        if not key:
            return handler()

        endpoint = self.get_idempotency_endpoint(request)
        req_hash = request_body_hash(request.data)

        record, created = IdempotencyKey.objects.get_or_create(
            user=request.user,
            endpoint=endpoint,
            key=key,
            defaults={
                "request_hash": req_hash,
                "state": IdempotencyKey.State.IN_PROGRESS,
            },
        )

        if not created:
            if record.request_hash != req_hash:
                raise ConflictException(
                    "Idempotency-Key was reused with a different request body.",
                    code=IDEMPOTENCY_KEY_REUSED,
                )
            if record.state == IdempotencyKey.State.COMPLETED:
                return Response(
                    record.response_body,
                    status=record.response_status,
                )
            raise ConflictException(
                "A request with this Idempotency-Key is already in progress.",
                code=IDEMPOTENCY_IN_PROGRESS,
            )

        try:
            response = handler()
        except Exception:
            # Releasing the key matters: leaving it IN_PROGRESS would make
            # every subsequent retry 409 forever, so one transient failure
            # would permanently block the operation.
            IdempotencyKey.objects.filter(pk=record.pk).delete()
            raise

        record.response_status = response.status_code
        record.response_body = json_safe(response.data)
        record.state = IdempotencyKey.State.COMPLETED
        record.save(
            update_fields=[
                "response_status",
                "response_body",
                "state",
                "updated_at",
            ]
        )
        return response
