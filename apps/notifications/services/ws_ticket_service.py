"""Single-use tickets for opening the notifications socket (SEC-4).

A browser cannot set headers on a WebSocket handshake, so it used to put
its access token in the URL, where proxies and servers write it to their
logs: a logged access token is a session for whoever reads the log. A
ticket is what goes in the URL instead. It is random, worthless after one
use, and dead after 60 seconds whether used or not, so a copy in a log is
spent before anyone can read it.

Tickets live in the shared cache. The web and socket processes must share
it (Redis, which CACHE_URL/REDIS_URL already selects); with the local-memory
fallback a ticket issued by one process is unknown to the other.
"""

import hashlib
import secrets

from django.core.cache import cache

TICKET_SECONDS = 60


def _key(ticket):
    # Stored by digest, so the cache never holds a usable ticket either.
    return "ws-ticket:" + hashlib.sha256(ticket.encode()).hexdigest()


class WebSocketTicketService:

    def issue(self, user):
        ticket = secrets.token_urlsafe(32)
        cache.set(_key(ticket), str(user.pk), timeout=TICKET_SECONDS)

        return {"ticket": ticket, "expires_in": TICKET_SECONDS}

    def redeem(self, ticket):
        """The user id the ticket was issued to, once; None after that.

        Delete decides it: when two handshakes race with one ticket, both
        may read it, but only one delete removes it.
        """
        if not ticket:
            return None

        key = _key(ticket)
        user_id = cache.get(key)

        if user_id is None or not cache.delete(key):
            return None

        return user_id
