"""Web S2/C5 against the running middleware, not just the settings."""

from django.test import TestCase, override_settings


@override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:3000"])
class CorsTests(TestCase):

    def preflight(self, origin):
        return self.client.options(
            "/api/v1/billing/plans",
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )

    def test_an_unknown_origin_gets_no_cors_answer(self):
        response = self.preflight("https://evil.example")

        self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_the_frontend_is_allowed_and_can_read_the_headers(self):
        response = self.client.get(
            "/api/v1/billing/plans", HTTP_ORIGIN="http://localhost:3000"
        )

        self.assertEqual(
            response["Access-Control-Allow-Origin"], "http://localhost:3000"
        )
        exposed = response["Access-Control-Expose-Headers"]
        self.assertIn("Retry-After", exposed)
        self.assertIn("Content-Disposition", exposed)
