"""The superseded search route is gone (E3-S7, E6-S10).

``providers/search/`` was a thin wrapper around the same
``ProviderService.list_providers(search=...)`` that ``providers/?search=``
already exposes, and the biller directory it stood in for is now
``vendors/directory-search/``. E3-S7, E6-S10 and the dashboard plan all called
it superseded; it had already been marked ``deprecated=True`` in the schema,
and removal was the step after that.

``providers/`` itself stays — the dashboard plan keeps it as the directory
cache.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.vendors.factories import UserFactory


class SupersededSearchRouteTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=UserFactory())

    def test_the_search_route_is_gone(self):
        self.assertEqual(
            self.client.get("/api/v1/providers/search/?q=chase").status_code,
            404,
        )

    def test_the_provider_list_still_works(self):
        """Kept deliberately as the directory cache."""
        self.assertEqual(
            self.client.get("/api/v1/providers/").status_code, 200
        )

    def test_the_list_still_searches(self):
        """What the removed route actually did, and still available."""
        self.assertEqual(
            self.client.get("/api/v1/providers/?search=chase").status_code,
            200,
        )

    def test_the_replacement_directory_search_works(self):
        """E3-S7, the endpoint that supersedes it."""
        self.assertEqual(
            self.client.get(
                "/api/v1/vendors/directory-search/?q=chase"
            ).status_code,
            200,
        )
