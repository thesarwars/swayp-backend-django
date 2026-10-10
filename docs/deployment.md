# Deploying Swayp

This is the whole path from a bare Ubuntu server to a working API. It assumes
Docker and a domain you control, and nothing else.

Everything here was verified against this repository — the settings guards, the
health endpoints, and the compose file were each exercised, not just written.

---

## 1. What runs where

Six containers, one image:

| Service | What it does | Published? |
|---|---|---|
| `web` | Gunicorn serving the API | `127.0.0.1:5010` only |
| `websocket` | Daphne serving `/ws/` only | `127.0.0.1:5011` only |
| `worker` | Celery — emails, check mailing, webhook side effects | no |
| `beat` | Celery beat — the nightly jobs (see §7) | no |
| `db` | Postgres 16 | **no** |
| `redis` | Redis 7 — Celery broker | **no** |

`migrate` is a seventh, short-lived service that runs once and exits.

`websocket` is separate from `web` on purpose. Serving the whole API from an
ASGI server would put every existing synchronous view behind a threadpool —
changing the request path of the entire product to add one feature. Splitting
them keeps HTTP on exactly the stack that is already tested, and means daphne
falling over costs live updates rather than the API. It is also optional: with
`REALTIME_ENABLED=false` you can simply not run it.

**Postgres and Redis are deliberately not published to the host.** They talk to
`web` over the private compose network, which is all they need. Publishing
`5432:5432` would put the database on the server's public interface, and
Postgres would then be reachable from the internet by anyone who found the
port — the password is the only thing standing in the way, and that is not a
position worth being in. If you need a psql shell, §8 shows how without opening
anything.

## 2. The port

The app listens on **5010** inside the container, and compose publishes it to
**127.0.0.1:5010** on the host — the loopback interface, not the public one.

This means nothing outside the machine can reach Gunicorn directly. A reverse
proxy on the host (nginx/Caddy) terminates TLS on 443 and forwards to
`127.0.0.1:5010`. That ordering matters: it is what keeps plain HTTP off the
wire, and it means a misconfigured firewall is not the only thing protecting
the app.

To change either half, set them in `.env` — no file edits:

```bash
APP_PORT=5010          # host port for the API
WS_PORT=5011           # host port for WebSockets
APP_BIND=127.0.0.1     # host interface for both
```

Set `APP_BIND=0.0.0.0` only if something else already terminates TLS in front
of the machine (a cloud load balancer). On a plain VPS, leave it.

## 3. Configuration

Copy `.env.example` to `.env` and fill it in. `config/settings/production.py`
**refuses to start** if any of the following is missing or unsafe, which is on
purpose — a service that will not boot gets fixed in ten minutes, whereas one
that boots with the development secret key is a problem nobody notices until
sessions are being forged.

Required, no fallbacks:

```bash
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_SECRET_KEY=          # python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
DJANGO_ALLOWED_HOSTS=api.getswayp.com
CORS_ALLOWED_ORIGINS=https://app.getswayp.com
FIELD_ENCRYPTION_KEYS=      # python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
FRONTEND_URL=https://app.getswayp.com
POSTGRES_PASSWORD=
```

Each refusal names the variable and how to produce a value, so a failed boot
tells you what to do rather than only that something is wrong.

Two of these are worth understanding rather than pasting:

- **`FIELD_ENCRYPTION_KEYS`** encrypts stored provider secrets. **Losing it
  makes existing encrypted rows permanently unreadable** — there is no reset.
  Back it up somewhere other than the server.
- **`CORS_ALLOWED_ORIGINS`** is the exact scheme+host of the frontend. Get it
  wrong and every browser call fails while the API answers `curl` perfectly.
  `CSRF_TRUSTED_ORIGINS` is derived from it, so the two cannot drift.

To take real money, add:

```bash
SUBSCRIPTION_BILLING_PROVIDER=stripe
STRIPE_SECRET_KEY=sk_live_...
STRIPE_BILLING_WEBHOOK_SECRET=whsec_...
```

Selecting `stripe` without both keys also refuses to boot. Without the webhook
secret specifically, subscriptions are created but never confirm as paid — a
silent failure that would otherwise surface as customers complaining that they
were charged and got nothing.

## 4. First deploy

```bash
git clone <repo> /srv/swayp && cd /srv/swayp
cp .env.example .env && vim .env          # §3

docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec web \
    python manage.py createsuperuser
```

Migrations run automatically in the `migrate` service, which exits before `web`
starts (`condition: service_completed_successfully`). They are **not** in the
image's `CMD`: with more than one `web` replica that would have every replica
racing to migrate the same database at once.

Confirm it came up:

```bash
curl -s localhost:5010/readyz     # {"status":"ok","database":true}
```

## 5. TLS and the reverse proxy

Caddy is the shorter path — it obtains and renews the certificate itself,
and needs no WebSocket-specific configuration beyond the second route:

```caddy
api.getswayp.com {
    reverse_proxy /ws/* 127.0.0.1:5011
    reverse_proxy 127.0.0.1:5010
}
```

nginx, if you already run it:

```nginx
server {
    listen 443 ssl http2;
    server_name api.getswayp.com;

    ssl_certificate     /etc/letsencrypt/live/api.getswayp.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.getswayp.com/privkey.pem;

    client_max_body_size 10M;   # receipt/attachment uploads

    location / {
        proxy_pass http://127.0.0.1:5010;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;   # required
    }

    # WebSockets go to daphne, not gunicorn. The Upgrade and Connection
    # headers are what turn an HTTP request into a socket; without them nginx
    # proxies it as an ordinary request and the client sees a 400 it cannot
    # explain. read_timeout must exceed the client's ping interval, or a quiet
    # but healthy connection is dropped every 60 seconds.
    location /ws/ {
        proxy_pass http://127.0.0.1:5011;
        proxy_http_version 1.1;
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        "upgrade";
        proxy_set_header Host              $host;
        proxy_set_header Origin            $http_origin;   # origin validation
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

`X-Forwarded-Proto` is not optional. Django is configured to read the scheme
from it (`SECURE_PROXY_SSL_HEADER`); without it Django sees plain HTTP behind
the proxy and redirects to HTTPS forever.

### HSTS

Production sends `Strict-Transport-Security: max-age=31536000` for the API
host by default. It promises only what the HTTPS redirect already enforces,
so it is safe from the first deploy. `DJANGO_HSTS_SECONDS=0` turns it off.

**Two flags are off by default, because they are hard to undo:**
- `DJANGO_HSTS_INCLUDE_SUBDOMAINS=True` makes every subdomain of the domain
  HTTPS-only for a year.
- `DJANGO_HSTS_PRELOAD=True` asks browsers to build the rule into their
  source, which takes months to remove.

Set them only once every subdomain serves HTTPS.

**A host running other settings sends no header from Django.** That includes
the dev host, which runs `config.settings.local`. Have nginx send it
instead, inside the `server { listen 443 … }` block:

```nginx
add_header Strict-Transport-Security "max-age=31536000" always;
```

`always` makes nginx add it to error responses too. Don't add it on the port
80 server block: a browser ignores it over plain HTTP.

## 5b. Notifications: push and realtime

Both are **off by default** and each is one variable.

### Push (mobile + web)

Firebase Cloud Messaging reaches iOS, Android and the browser Push API through
one integration, so there is a single credential rather than one per platform.

```bash
PUSH_PROVIDER=fcm
PUSH_ENABLED=true
FCM_CREDENTIALS_FILE=/run/secrets/firebase.json   # or FCM_CREDENTIALS_JSON={...}
```

Get the file from the Firebase console: *Project settings → Service accounts →
Generate new private key*. Mount it read-only; it is a credential, not config.

**Before turning `PUSH_ENABLED` on, read the warning in `config/settings/base.py`
above the flag.** Reminder idempotency lives on the `Notification` row, and a
user who has in-app notifications switched off has no row — so with push on,
that user is re-notified every single day. The same precondition already
applies to `NOTIFICATION_EMAIL_ENABLED`.

### Realtime (live in-app updates)

```bash
REALTIME_ENABLED=true
```

Then run the `websocket` service and add the `/ws/` proxy route above. Redis
carries the fan-out, so a notification written by the Celery worker reaches a
browser connected to the daphne process — without a shared channel layer it
would reach nobody most of the time.

With `REALTIME_ENABLED=false` the socket refuses connections with code `4503`
rather than accepting and staying silent, so a misconfiguration is visible to
the client instead of looking like a backend that is broken.

## 6. Health checks

Two endpoints, unversioned, no auth:

| Path | Answers | Use it for |
|---|---|---|
| `/healthz` | is the process alive | restart policy |
| `/readyz` | is the database reachable | load-balancer rotation |

They are separate because the questions are. `/healthz` touches no dependency,
so a brief database blip does not get the container killed and restarted —
restarting fixes a wedged process, and it does nothing at all for a database
that is down. `/readyz` returns `503` while the database is unreachable, which
takes the instance out of rotation without killing it; it reports the failure
as a boolean and never echoes the connection error, since that string contains
the host and username.

The image's `HEALTHCHECK` uses `/healthz`, for the same reason.

## 7. Scheduled work

`beat` runs six jobs, all on **America/New_York** time. If `beat` is not
running, every one of them fails silently — nothing errors, the work simply
never happens, which is the hardest kind of outage to notice:

| Job | When (ET) | Consequence if it stops |
|---|---|---|
| `billing.renew_subscriptions` | 00:30 | **Free check allowances never reset** |
| `bills.generate_occurrences` | 03:00 | Upcoming bills stop appearing |
| `payments.autopay_scheduler` | 04:00 | Autopay silently stops paying |
| `payments.release_scheduled_payments` | 04:30 | Future-dated sends never leave |
| `notifications.bill_status_notifier` | 05:00 | Due/overdue reminders stop |
| `payments.reconcile_payments` | hourly, :15 | Payments stay `PROCESSING` forever |

The order is load-bearing, not arbitrary: occurrences must exist before autopay
reads them, and reminders run last so a bill that already has money moving does
not also get chased. Do not re-time these without reading the comments in
`config/settings/base.py`.

The schedule is defined in Eastern because the product's cutoffs are
(11:59 PM ET), so `CELERY_TIMEZONE` must stay `America/New_York` regardless of
where the server is.

`beat_data` is a named volume holding beat's "when did each task last run"
state. Keep it across deploys — a fresh volume can re-run a job or skip one.

## 8. Operating

```bash
C="docker compose -f docker-compose.prod.yml"

$C logs -f web                  # follow
$C ps                           # what is up
$C exec web python manage.py shell
$C exec db psql -U swayp swayp  # psql without publishing 5432
```

Deploy a new version:

```bash
git pull
$C up -d --build       # migrate re-runs, then web restarts
```

Back up — do this on a schedule, not by hand:

```bash
$C exec -T db pg_dump -U swayp swayp | gzip > swayp-$(date +%F).sql.gz
```

A backup nobody has restored is a hypothesis. Restore one into a scratch
database before you need to.

## 9. Before going live

- [ ] `.env` filled in; `docker compose -f docker-compose.prod.yml config -q` is silent
- [ ] `curl https://api.getswayp.com/readyz` returns `ok` **over HTTPS**
- [ ] The frontend can log in from a browser — this is the real CORS test
- [ ] `FIELD_ENCRYPTION_KEYS` backed up off the server
- [ ] Stripe webhook endpoint registered at `/webhooks/stripe/billing` and its
      secret in `.env`; send a test event and confirm a `200`
- [ ] `beat` is in `docker compose ps` and stays up
- [ ] `pg_dump` scheduled, and one restore actually tried
- [ ] Only 22/80/443 open on the host firewall — **not 5010, 5011, 5432, or 6379**
- [ ] If realtime is on: `websocket` is up, and a browser can open
      `wss://api.getswayp.com/ws/notifications/?token=…`
- [ ] If push is on: a test notification arrives on a real device
- [ ] HSTS header present: `curl -sI https://<host>/healthz | grep -i strict` (§5)

## 10. When something is wrong

| Symptom | Cause |
|---|---|
| `web` exits at boot, `ImproperlyConfigured` in logs | Read it — it names the variable. This is the guard working. |
| Browser calls fail, `curl` works | `CORS_ALLOWED_ORIGINS` is not the frontend's exact scheme+host |
| `DisallowedHost` | Add the domain to `DJANGO_ALLOWED_HOSTS` |
| Infinite HTTPS redirect | Proxy is not sending `X-Forwarded-Proto` (§5) |
| `/readyz` is `503`, `/healthz` is `200` | App is fine, database is not: `$C logs db` |
| Subscriptions stick at `incomplete` | Webhook not reaching `/webhooks/stripe/billing`, or wrong secret |
| Free check counts never reset | `beat` is not running (§7) |
