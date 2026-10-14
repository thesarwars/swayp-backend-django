"""Web §4: a person can set and remove their own profile picture."""

import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.vendors.factories import UserFactory

MEDIA = tempfile.mkdtemp()


def png(name="me.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "teal").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=MEDIA)
class ProfilePictureTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def upload(self, file):
        return self.client.post("/api/v1/users/profile/picture",
                                {"profile_picture": file}, format="multipart")

    def test_upload_shows_on_the_summary_and_is_served(self):
        response = self.upload(png())

        self.assertEqual(response.status_code, 200, response.content)
        url = response.json()["data"]["profile_picture"]
        self.assertTrue(url.startswith("http://testserver/media/profile_pictures/"))

        summary = self.client.get("/api/v1/dashboard/profile-summary").json()
        self.assertEqual(summary["data"]["profile_picture"], url)

        served = self.client.get(url.replace("http://testserver", ""))
        self.assertEqual(served.status_code, 200)

    def test_replacing_deletes_the_old_file(self):
        first = self.upload(png()).json()["data"]["profile_picture"]
        self.upload(png("again.png"))

        old = self.client.get(first.replace("http://testserver", ""))
        self.assertEqual(old.status_code, 404)

    def test_remove(self):
        self.upload(png())

        data = self.client.delete("/api/v1/users/profile/picture").json()["data"]

        self.assertIsNone(data["profile_picture"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile_picture)

    def test_not_an_image_is_refused(self):
        response = self.upload(
            SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("profile_picture", response.json()["errors"])
