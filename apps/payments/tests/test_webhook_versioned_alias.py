"""The versioned mount is an alias, not a move.

The processor dashboards were configured against /api/v1/webhooks/..., and a
webhook URL is the one thing that cannot be fixed faster on our side than on
theirs — every event sent to a dead URL is a payment that never confirms. So
both paths answer.

The canonical mount stays versionless, and `reverse()` still returns it, so
nothing internal starts emitting a URL that would move with an API version.
"""

from django.test import TestCase
from django.urls import reverse


class VersionedWebhookAliasTests(TestCase):

    PROCESSORS = ("moov", "stripe", "lob", "plaid", "mock")

    def test_both_mounts_answer(self):
        for slug in self.PROCESSORS:
            for url in (
                f"/webhooks/{slug}",
                f"/api/v1/webhooks/{slug}",
            ):
                with self.subTest(url=url):
                    response = self.client.post(
                        url, data="{}", content_type="application/json"
                    )

                    # 400 = routed and refusing an unsigned body, which is the
                    # correct answer. 404 would mean the route is not there.
                    self.assertNotEqual(response.status_code, 404)

    def test_reverse_still_gives_the_versionless_path(self):
        """Or an emailed or stored URL would start moving with the version."""
        self.assertEqual(reverse("webhook-moov"), "/webhooks/moov")
        self.assertEqual(reverse("webhook-plaid"), "/webhooks/plaid")

    def test_the_alias_has_its_own_names(self):
        """Two registrations sharing one name would silently win reverse()."""
        self.assertEqual(
            reverse("webhook-moov-v1"), "/api/v1/webhooks/moov"
        )

    def test_an_unsigned_call_is_refused_on_the_alias_too(self):
        """The alias must not be a way around the signature check."""
        response = self.client.post(
            "/api/v1/webhooks/moov",
            data="{}",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
