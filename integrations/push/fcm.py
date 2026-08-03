"""Firebase Cloud Messaging adapter (E8-S5).

One integration reaches all three clients: FCM forwards to APNs for iOS, to
Android transport directly, and to the browser Push API for web. The service
account credential is the only thing that has to change to go live.

``firebase-admin`` is imported inside the methods, not at module scope, for
the same reason the Stripe adapter is: a deployment running on the mock
provider must not need the SDK installed. The factory imports this module
lazily as well, so this file is only touched when PUSH_PROVIDER=fcm.
"""

from __future__ import annotations

import json
import logging
import threading

from django.conf import settings

from integrations.push.base import PushMessage, PushProvider, PushResult

logger = logging.getLogger(__name__)

#: firebase_admin keeps global app state, and initialize_app() raises if it is
#: called twice. Gunicorn's gthread workers make that a real race rather than a
#: theoretical one, so initialisation happens once behind a lock.
_init_lock = threading.Lock()
_app = None


def _credentials_payload():
    """The service-account JSON, from a file path or an inline blob.

    Both are supported because the two deployment styles genuinely differ: a
    server has a mounted file, a platform like Heroku or Cloud Run only has
    environment variables, and forcing either to fake the other is how
    credentials end up committed.
    """
    raw = getattr(settings, "FCM_CREDENTIALS_JSON", "") or ""

    if raw.strip().startswith("{"):
        return json.loads(raw)

    path = getattr(settings, "FCM_CREDENTIALS_FILE", "") or ""

    if path:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    return None


class FCMPushProvider(PushProvider):
    name = "fcm"

    def is_configured(self) -> bool:
        try:
            return _credentials_payload() is not None
        except (OSError, ValueError):
            logger.exception("fcm: credentials are present but unreadable")
            return False

    def _app_handle(self):
        global _app

        if _app is not None:
            return _app

        with _init_lock:
            # Re-checked inside the lock: two threads can both pass the check
            # above, and the second initialize_app() would raise.
            if _app is not None:
                return _app

            import firebase_admin
            from firebase_admin import credentials

            payload = _credentials_payload()

            if payload is None:
                return None

            _app = firebase_admin.initialize_app(
                credentials.Certificate(payload),
                name="swayp-push",
            )

        return _app

    def send(self, message: PushMessage) -> PushResult:
        if not message.tokens:
            return PushResult(detail="no tokens")

        try:
            from firebase_admin import messaging
        except ImportError:
            logger.error(
                "fcm: PUSH_PROVIDER=fcm but firebase-admin is not installed"
            )
            return PushResult(failed=len(message.tokens), detail="sdk missing")

        app = self._app_handle()

        if app is None:
            logger.error("fcm: no credentials configured")
            return PushResult(
                failed=len(message.tokens), detail="not configured"
            )

        # Values are coerced to str because FCM rejects a data payload that
        # holds anything else, and the caller's context legitimately carries
        # Decimals and dates.
        data = {str(k): str(v) for k, v in (message.data or {}).items()}

        request = messaging.MulticastMessage(
            tokens=list(message.tokens),
            notification=messaging.Notification(
                title=message.title, body=message.body
            ),
            data=data,
        )

        try:
            response = messaging.send_each_for_multicast(request, app=app)
        except Exception:
            # Never raises into the caller — a push failure must not roll back
            # the payment that triggered it.
            logger.exception("fcm: multicast send failed")
            return PushResult(
                failed=len(message.tokens), detail="send failed"
            )

        rejected = []

        for token, result in zip(message.tokens, response.responses):
            if result.success:
                continue

            # UNREGISTERED and invalid-argument are terminal: the app was
            # uninstalled, or the token was never valid. Anything else —
            # quota, unavailable, internal — is transient and the row must
            # survive it, or a Firebase incident would silently unsubscribe
            # every device the product has.
            name = type(result.exception).__name__

            if name in ("UnregisteredError", "SenderIdMismatchError"):
                rejected.append(token)

        return PushResult(
            sent=response.success_count,
            failed=response.failure_count,
            rejected_tokens=tuple(rejected),
            detail="fcm",
        )
