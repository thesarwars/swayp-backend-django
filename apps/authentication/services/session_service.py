"""Sessions: one row per signed-in device, and ending them.

Every token pair carries the session's id as the ``sid`` claim. simplejwt
copies it from the refresh token into each access token it mints and keeps it
through rotation, so a device keeps one session for as long as it stays
signed in.

Ending a session works on both tokens at once. The refresh token is refused
at the next refresh, and the access token is refused on the next request
(``SessionJWTAuthentication``), not when its own lifetime runs out. Tokens
minted before sessions carried an id have no ``sid``; they are adopted into a
session at their next refresh and age out on their own until then.
"""

import datetime as dt

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import RefreshToken as Session
from apps.common.request_meta import client_ip, user_agent

SID_CLAIM = "sid"

#: How stale last_used_at may get before a request writes it again. Writing
#: on every request would turn every read into a write for a timestamp the
#: sessions screen shows to the minute at best.
TOUCH_INTERVAL = dt.timedelta(minutes=5)


def token_pair(refresh):
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


class SessionService:

    @staticmethod
    @transaction.atomic
    def start(user, request):
        """Open a session for ``user`` on this device; returns its refresh
        token, which carries the session id."""
        now = timezone.now()
        refresh = RefreshToken.for_user(user)
        session = Session(
            user=user,
            user_agent=user_agent(request),
            ip_address=client_ip(request),
            expires_at=now + refresh.lifetime,
            last_used_at=now,
        )
        refresh[SID_CLAIM] = str(session.id)
        session.token_hash = make_password(str(refresh))
        session.save()

        return refresh

    @staticmethod
    @transaction.atomic
    def rotated(tokens, request=None):
        """Record a refresh: the serializer has already rotated the token.

        A refresh for an ended session is refused (TokenError) and the token
        it just rotated to is blacklisted, so ending a session cannot be
        outrun by refreshing first.
        """
        refresh = RefreshToken(tokens["refresh"])
        sid = refresh.get(SID_CLAIM)
        now = timezone.now()

        if sid is None:
            # Minted before sessions carried an id: adopt it into one.
            from apps.authentication.services.refresh_token_service import (
                token_user,
            )

            session = Session(
                user=token_user(refresh),
                user_agent=user_agent(request),
                ip_address=client_ip(request),
                expires_at=now + refresh.lifetime,
                last_used_at=now,
            )
            refresh[SID_CLAIM] = str(session.id)
            session.token_hash = make_password(str(refresh))
            session.save()

            return token_pair(refresh)

        session = (
            Session.objects.select_for_update()
            .filter(id=sid, revoked_at__isnull=True)
            .first()
        )

        if session is None:
            refresh.blacklist()
            raise TokenError("This session has been signed out.")

        session.token_hash = make_password(str(refresh))
        session.expires_at = now + refresh.lifetime
        session.last_used_at = now
        session.ip_address = client_ip(request) or session.ip_address
        session.save(
            update_fields=[
                "token_hash", "expires_at", "last_used_at", "ip_address",
                "updated_at",
            ]
        )

        return {"access": str(tokens["access"]), "refresh": str(refresh)}

    @staticmethod
    def is_live(sid):
        """Is the session behind an access token still signed in?

        One primary-key read per authenticated request, plus an occasional
        write to keep last_used_at roughly current.
        """
        row = (
            Session.objects.filter(id=sid, revoked_at__isnull=True)
            .values("last_used_at")
            .first()
        )

        if row is None:
            return False

        now = timezone.now()
        last_used = row["last_used_at"]

        if last_used is None or now - last_used > TOUCH_INTERVAL:
            Session.objects.filter(id=sid).update(last_used_at=now)

        return True

    @staticmethod
    def active(user):
        return Session.objects.filter(
            user=user,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).order_by("-last_used_at", "-created_at")

    @staticmethod
    def end(user, session_id):
        """Sign out one of ``user``'s sessions. False if there is no such
        live session of theirs."""
        return bool(
            Session.objects.filter(
                user=user, id=session_id, revoked_at__isnull=True
            ).update(revoked_at=timezone.now())
        )

    @staticmethod
    def end_all(user, keep=None):
        """Sign out every session of ``user``'s, except ``keep`` (a session
        id). Returns how many ended."""
        sessions = Session.objects.filter(user=user, revoked_at__isnull=True)

        if keep is not None:
            sessions = sessions.exclude(id=keep)

        return sessions.update(revoked_at=timezone.now())
