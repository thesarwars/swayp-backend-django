"""Production settings refuse to boot on an unsafe value (deployment).

The direction matters: a service that will not start is an incident someone
fixes in ten minutes, whereas one that starts with the development secret key
is an incident nobody notices until sessions are being forged. Each of these
asserts that the refusal actually happens, because a guard nobody exercises is
a guard that has never been shown to work.
"""

import importlib
import os
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

GOOD = {
    "DJANGO_SECRET_KEY": "x" * 60,
    "DJANGO_ALLOWED_HOSTS": "api.getswayp.com",
    "CORS_ALLOWED_ORIGINS": "https://app.getswayp.com",
    "FIELD_ENCRYPTION_KEYS": "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleTEyMzQ1Ng==",
    "FRONTEND_URL": "https://app.getswayp.com",
    "DEFAULT_PLAN_CODE": "FOUNDING",
    "SUBSCRIPTION_BILLING_PROVIDER": "mock",
}


def load(**overrides):
    env = {**GOOD, **overrides}
    env = {k: v for k, v in env.items() if v is not None}

    with mock.patch.dict(os.environ, env, clear=False):
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)

        module = importlib.import_module("config.settings.production")

        return importlib.reload(module)


class ProductionGuardTests(SimpleTestCase):

    def test_a_complete_configuration_loads(self):
        settings = load()

        self.assertFalse(settings.DEBUG)
        self.assertEqual(settings.ALLOWED_HOSTS, ["api.getswayp.com"])

    def test_it_refuses_without_a_secret_key(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            load(DJANGO_SECRET_KEY=None)

        self.assertIn("DJANGO_SECRET_KEY", str(ctx.exception))

    def test_it_refuses_the_development_secret_key(self):
        """base.py ships one, and it is in the repository."""
        with self.assertRaises(ImproperlyConfigured) as ctx:
            load(DJANGO_SECRET_KEY="django-insecure-abc123")

        self.assertIn("development key", str(ctx.exception))

    def test_it_refuses_without_allowed_hosts(self):
        """Empty + DEBUG=False means Django rejects every request, so the
        service would start and serve nothing."""
        with self.assertRaises(ImproperlyConfigured) as ctx:
            load(DJANGO_ALLOWED_HOSTS=None)

        self.assertIn("DJANGO_ALLOWED_HOSTS", str(ctx.exception))

    def test_it_refuses_without_cors_origins(self):
        """Without it the frontend is blocked while every test still passes."""
        with self.assertRaises(ImproperlyConfigured) as ctx:
            load(CORS_ALLOWED_ORIGINS=None)

        self.assertIn("CORS_ALLOWED_ORIGINS", str(ctx.exception))

    def test_it_refuses_without_encryption_keys(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            load(FIELD_ENCRYPTION_KEYS=None)

        self.assertIn("FIELD_ENCRYPTION_KEYS", str(ctx.exception))

    def test_it_refuses_a_localhost_frontend_url(self):
        """Invite emails would carry a link that is dead in the recipient's
        inbox."""
        with self.assertRaises(ImproperlyConfigured) as ctx:
            load(FRONTEND_URL="http://localhost:3000")

        self.assertIn("FRONTEND_URL", str(ctx.exception))

    def test_it_refuses_without_a_frontend_url(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            load(FRONTEND_URL=None)

        self.assertIn("FRONTEND_URL", str(ctx.exception))

    def test_it_refuses_an_over_entitling_default_plan(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            load(DEFAULT_PLAN_CODE="ENTERPRISE")

        self.assertIn("FOUNDING", str(ctx.exception))

    def test_selecting_stripe_without_keys_fails_at_boot(self):
        """Rather than at a customer's first subscribe."""
        with self.assertRaises(ImproperlyConfigured) as ctx:
            load(
                SUBSCRIPTION_BILLING_PROVIDER="stripe",
                STRIPE_SECRET_KEY=None,
            )

        self.assertIn("STRIPE_SECRET_KEY", str(ctx.exception))

    def test_selecting_stripe_without_a_webhook_secret_fails_at_boot(self):
        """Without it, subscriptions never confirm as paid."""
        with self.assertRaises(ImproperlyConfigured) as ctx:
            load(
                SUBSCRIPTION_BILLING_PROVIDER="stripe",
                STRIPE_SECRET_KEY="sk_live_x",
                STRIPE_BILLING_WEBHOOK_SECRET=None,
            )

        self.assertIn("STRIPE_BILLING_WEBHOOK_SECRET", str(ctx.exception))


class TransportSecurityTests(SimpleTestCase):

    def test_cookies_are_secure_only(self):
        settings = load()

        self.assertTrue(settings.SESSION_COOKIE_SECURE)
        self.assertTrue(settings.CSRF_COOKIE_SECURE)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)

    def test_it_trusts_the_proxy_scheme_header(self):
        """Behind a TLS-terminating balancer Django sees plain HTTP and would
        otherwise redirect forever."""
        settings = load()

        self.assertEqual(
            settings.SECURE_PROXY_SSL_HEADER,
            ("HTTP_X_FORWARDED_PROTO", "https"),
        )

    def test_hsts_is_off_until_asked_for(self):
        """Browsers remember it and it cannot be withdrawn quickly, so a
        first deploy must not be able to lock a domain out by accident."""
        settings = load()

        self.assertEqual(settings.SECURE_HSTS_SECONDS, 0)
        self.assertFalse(settings.SECURE_HSTS_PRELOAD)

    def test_enabling_hsts_turns_on_subdomains_and_preload(self):
        settings = load(DJANGO_HSTS_SECONDS="31536000")

        self.assertTrue(settings.SECURE_HSTS_INCLUDE_SUBDOMAINS)
        self.assertTrue(settings.SECURE_HSTS_PRELOAD)

    def test_csrf_trusted_origins_follow_cors(self):
        """Derived rather than configured twice, so they cannot drift."""
        settings = load()

        self.assertEqual(
            settings.CSRF_TRUSTED_ORIGINS, settings.CORS_ALLOWED_ORIGINS
        )


class HealthProbeReachabilityTests(SimpleTestCase):
    """The probes have to answer over plain HTTP.

    Docker's HEALTHCHECK, a load balancer target check and a k8s probe all
    connect to the container directly, so none of them sets
    X-Forwarded-Proto and SECURE_SSL_REDIRECT would answer 301 before Django
    ever ran. ``curl -f`` treats a 301 as success, so the probe passes while
    testing nothing — a check that cannot fail is worse than no check.
    """

    def test_the_probe_paths_are_exempt_from_the_ssl_redirect(self):
        settings = load()

        self.assertEqual(
            settings.SECURE_REDIRECT_EXEMPT, [r"^healthz$", r"^readyz$"]
        )

    def test_the_exempt_patterns_match_the_real_paths(self):
        """Django matches these against the path with the leading slash
        stripped, so a pattern written as "^/healthz$" silently never matches
        and the setting looks correct while doing nothing."""
        import re

        settings = load()
        patterns = [re.compile(p) for p in settings.SECURE_REDIRECT_EXEMPT]

        for path in ("healthz", "readyz"):
            with self.subTest(path=path):
                self.assertTrue(
                    any(p.search(path) for p in patterns),
                    f"/{path} would still be redirected",
                )

    def test_nothing_else_is_exempt(self):
        """An over-broad pattern would quietly serve real endpoints over
        plain HTTP."""
        import re

        settings = load()
        patterns = [re.compile(p) for p in settings.SECURE_REDIRECT_EXEMPT]

        for path in ("api/v1/auth/login/", "api/v1/payments/", "admin/"):
            with self.subTest(path=path):
                self.assertFalse(any(p.search(path) for p in patterns))
