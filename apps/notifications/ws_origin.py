"""Origin check for the notifications socket, browser handshakes only (DASH-3).

The origin check exists because a browser opens a WebSocket from any page,
with no same-origin policy, so any site a signed-in user visits could open
one here. It is a browser defence.

A native app is not a browser, and it fails that check for reasons that have
nothing to do with an attack. React Native sends no Origin at all, or the API
host itself as Origin, and neither is the frontend's origin that the
allow-list names. So the mobile app was refused before its token was read.

A handshake carrying an Authorization header cannot come from a browser page:
the browser WebSocket API has no way to set one. Such a handshake skips the
origin check and is authenticated by its token in the consumer, as before.
Everything else, which includes every browser connection using ?token=, is
checked exactly as it was.
"""

from channels.security.websocket import OriginValidator


def has_authorization_header(scope):
    return any(
        name == b"authorization" for name, _ in scope.get("headers", [])
    )


class BrowserOriginValidator(OriginValidator):

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "websocket" and has_authorization_header(scope):
            return await self.application(scope, receive, send)

        return await super().__call__(scope, receive, send)
