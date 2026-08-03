# E8 — Realtime Notifications (Push + WebSocket)

Notifications reach a user through **three** paths, and they are not
alternatives to each other. Each covers a case the others cannot.

| Path | Works when | Platforms |
|---|---|---|
| **Push (FCM)** | app is closed, backgrounded, or open | iOS, Android, web |
| **WebSocket** | app is open and focused | web, mobile |
| **REST poll** | always — the fallback and the source of truth | all |

Push is the one that matters most for this product: a failed payment at 2am
has to reach someone who is not looking at their screen. The WebSocket exists
so a badge count changes while you watch, without a round trip.

**Both are off until the server enables them.** Build against them, but do not
assume they are on — the REST list must keep working on its own.

---

## 1. Push notifications

### 1.1 Register the device

Call this **on every app launch**, not only after sign-in. FCM rotates tokens,
and a client that registers once will go quiet with no error to notice.

```http
POST /api/v1/notifications/devices/register/
Authorization: Bearer <access>

{
  "token": "<FCM registration token>",
  "platform": "IOS",          // IOS | ANDROID | WEB
  "deviceName": "iPhone 15"   // optional, for a future "your devices" screen
}
```

```json
{
  "id": "3f2b…",
  "platform": "IOS",
  "deviceName": "iPhone 15",
  "isActive": true,
  "lastSeenAt": "2026-08-01T10:04:00Z"
}
```

The token is never echoed back. It is a bearer string — anyone holding it can
send to that device — so it does not belong in a response body or a log.

Registering the same token twice does not create a second row. If the token is
already registered to **another account**, it is *moved* to the caller. That is
what makes signing in on a shared device stop the previous user's bill
reminders from arriving on it.

### 1.2 Unregister on sign-out

```http
POST /api/v1/notifications/devices/unregister/
{ "token": "<the same token>" }
```

**Do not skip this.** Without it, the next person to sign in on that device
keeps receiving the previous user's notifications until the token rotates —
and on a shared office tablet that is somebody else's payment history.

Always returns `200`, even for a token that was never registered: whether a
token exists is not something this endpoint will reveal.

### 1.3 The payload you receive

```json
{
  "notification": { "title": "Payment failed", "body": "…" },
  "data": {
    "type": "PAYMENT_FAILED",
    "notificationId": "9a1c…",
    "paymentId": "44de…"
  }
}
```

`data` carries **identifiers only** — never amounts, vendor names, or balances.
A push payload travels through Apple's and Google's infrastructure and is
visible to the OS and on the lock screen. Use the ids to deep-link, then fetch
the real content over the authenticated API.

### 1.4 Enabling it per user

Push respects notification preferences like any other channel, and **defaults
to off**:

```http
PATCH /api/v1/notifications/preferences/
{ "preferences": [ { "type": "PAYMENT_FAILED", "push": true } ] }
```

Read `GET /api/v1/notifications/preferences/` first and check
`channels.push.supported`. If it is `false`, the deployment has no push
adapter — hide the toggle rather than showing one that returns `400`.

`supported` and `enabled` are different facts: `supported` means the server
has an adapter, `enabled` means the release switch is on.

---

## 2. WebSocket

### 2.1 Connect

```
wss://api.getswayp.com/ws/notifications/?token=<access JWT>
```

The token goes in the **query string** because the browser WebSocket API
cannot set an `Authorization` header. There is no supported alternative — this
is why the standard practice is a short-lived *access* token here. Never send
a refresh token.

On success the server sends:

```json
{ "type": "connected" }
```

Wait for that before treating the socket as live. An open socket and an
authenticated one are different things, and only one of them delivers
notifications.

### 2.2 Receiving

```json
{
  "type": "notification",
  "notification": {
    "id": "9a1c…",
    "type": "PAYMENT_FAILED",
    "title": "Payment failed",
    "message": "…",
    "isRead": false,
    "createdAt": "2026-08-01T10:04:00Z",
    "metadata": { }
  }
}
```

This is the **same row** `GET /api/v1/notifications/` returns, serialised in
one place — so the socket and the list cannot disagree. Insert it at the top
of your list and increment the unread badge; no refetch needed.

### 2.3 Close codes — handle these distinctly

| Code | Meaning | What to do |
|---|---|---|
| `4401` | Token invalid, expired, or account deactivated | Refresh the token, then reconnect **once** |
| `4503` | Realtime disabled on this deployment | Stop reconnecting. Fall back to polling |
| `1006` | Network dropped | Reconnect with backoff |

Treating `4401` as a network error is the mistake to avoid: the client
reconnects forever with the same dead token and hammers the server.
Treating `4503` as retryable is the same bug with a different cause.

### 2.4 Keepalive

```json
→ { "type": "ping" }
← { "type": "pong" }
```

Send one every ~30 seconds. Proxies close idle connections, and without this
a healthy socket disappears silently. Anything else you send is ignored rather
than closing the connection.

### 2.5 Reconnect strategy

```js
let delay = 1000;

function connect() {
  const ws = new WebSocket(`${WS_URL}?token=${accessToken}`);

  ws.onopen = () => { delay = 1000; };

  ws.onclose = (e) => {
    if (e.code === 4503) return;                 // disabled — stop
    if (e.code === 4401) { refreshThenConnect(); return; }

    setTimeout(connect, delay);
    delay = Math.min(delay * 2, 30000);          // cap the backoff
  };
}
```

**Always refetch the list on reconnect.** Anything that happened while the
socket was down was not delivered — the server does not replay. This is the
single most common realtime bug, and it shows up as notifications that are
silently missing rather than as an error.

---

## 3. What to build

The three paths layer, they do not replace each other:

1. **REST list is the source of truth.** Fetch on mount, on reconnect, and
   when the app returns to the foreground. Everything below is an optimisation
   on top of it.
2. **WebSocket for live updates** when the app is open. If it is unavailable,
   nothing breaks.
3. **Push for everything else** — closed app, backgrounded app, locked phone.

A user with a socket open *and* push enabled may see both for one event. Dedupe
on `notificationId`; both carry the same one, which is why it is in the push
payload.

### Do not

- Rely on the socket for correctness — it is best-effort, and a dropped
  connection means missed events.
- Show push `data` values as content — they are identifiers, deliberately.
- Reconnect on `4503`.
- Skip unregister on sign-out.

---

## 4. Server switches

| Setting | Default | Effect when off |
|---|---|---|
| `PUSH_ENABLED` | `false` | Preferences accept `push: true`, nothing is delivered |
| `REALTIME_ENABLED` | `false` | Socket refuses with `4503` |

Ask the backend which are on in the environment you are targeting. Both were
built to be turned on without a code change on either side.
