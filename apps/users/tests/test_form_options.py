"""Web §4: the form choice lists are public and value/label pairs."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.common.tests.openapi_contract import assert_matches_schema


class FormOptionsTests(TestCase):

    def test_public_and_shaped(self):
        response = APIClient().get("/api/v1/options")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        for key in ("industries", "business_sizes", "business_types"):
            self.assertTrue(data[key])
            self.assertEqual(set(data[key][0]), {"value", "label"})
        assert_matches_schema(self, response, "GET", "/api/v1/options")
