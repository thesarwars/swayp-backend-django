FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5010

WORKDIR /app

# libpq-dev for psycopg2-binary, libzbar0 for pyzbar (QR decoding — the one
# system dependency that is easy to miss and fails only at runtime).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libzbar0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Requirements before the source, so a code change does not reinstall the
# whole dependency tree.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Not root. A container that is compromised should not also be privileged.
#
# /var/lib/celery is created here rather than left to the volume mount. Docker
# seeds a named volume with the ownership of the image directory underneath it,
# and creates it root-owned when there is no such directory — so beat would
# start, then die on Permission denied writing its schedule.
RUN useradd --create-home --uid 10001 swayp \
    && mkdir -p /app/staticfiles /app/media /var/lib/celery \
    && chown -R swayp:swayp /app /var/lib/celery
USER swayp

EXPOSE 5010

# Liveness, not readiness: this must not fail because the database is down.
# Restarting a web process does not fix a broken database, and cycling every
# container during a blip turns a degraded service into an outage.
#
# The body is matched, not just the status. `curl -f` only fails on 4xx/5xx, so
# a 301 from the HTTPS redirect would satisfy it without ever reaching Django —
# the container would report healthy whatever state the app was in. Requiring
# the payload means only a real answer from the view passes.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS --max-time 4 http://localhost:${PORT}/healthz \
        | grep -q '"status": *"ok"' || exit 1

# gunicorn, not runserver. The dev server is single-threaded, reloads on file
# changes and is explicitly not for production — and it was what this image
# ran until now, with gunicorn installed and never invoked.
#
# Migrations are NOT run here: with more than one replica they would race.
# Run them as a release step (see docker-compose.prod.yml's `migrate` service).
CMD ["sh", "-c", "gunicorn config.wsgi:application \
    --bind 0.0.0.0:${PORT} \
    --workers ${GUNICORN_WORKERS:-3} \
    --threads ${GUNICORN_THREADS:-4} \
    --timeout ${GUNICORN_TIMEOUT:-60} \
    --access-logfile - --error-logfile - \
    --forwarded-allow-ips '*'"]
