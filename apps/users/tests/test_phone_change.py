"""AUTH-10 — adding or changing the phone number after registration.

An account created without a phone could never use phone sign-in. The number
is a login identifier, so setting it takes a code: requested for one number,
spendable only on that number.
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.models import OTP, OTPPurpose
from apps.vendors.factories import UserFactory

REQUEST_URL = "/api/v1/users/profile/phone"
VERIFY_URL = "/api/v1/users/profile/phone/verify"
NUMBER = "+14155552671"
OTHER_NUMBER = "+14155550000"
CODE = "123456"


@patch(
    "apps.authentication.services.otp_delivery_service.OTPService.generate_otp",
    return_value=CODE,
)
class PhoneChangeTests(TestCase):

    def setUp(self):
        self.user = UserFactory(email="ada@example.com")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _request(self, number=NUMBER):
        return self.client.post(REQUEST_URL, {"phone_number": number})

    def _verify(self, number=NUMBER, otp=CODE):
        return self.client.post(
            VERIFY_URL, {"phone_number": number, "otp": otp}
        )

    def test_an_account_without_a_phone_can_add_one(self, _):
        response = self._request()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["email"], "a***a@example.com")

        response = self._verify()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["phone_number"], NUMBER)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone_number, NUMBER)

    def test_an_existing_number_can_be_changed(self, _):
        self.user.phone_number = OTHER_NUMBER
        self.user.save(update_fields=["phone_number"])

        self._request()
        self._verify()

        self.user.refresh_from_db()
        self.assertEqual(self.user.phone_number, NUMBER)

    def test_the_code_is_bound_to_the_number_it_was_requested_for(self, _):
        self._request(NUMBER)

        response = self._verify(number=OTHER_NUMBER)

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.phone_number)

    def test_a_wrong_code_is_counted_and_changes_nothing(self, _):
        self._request()

        response = self._verify(otp="000000")

        self.assertEqual(response.status_code, 400)
        otp = OTP.objects.get(user=self.user, purpose=OTPPurpose.PHONE_CHANGE)
        self.assertEqual(otp.attempts, 1)
        self.assertIsNone(otp.used_at)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.phone_number)

    def test_an_expired_code_is_refused(self, _):
        self._request()
        OTP.objects.filter(user=self.user).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        response = self._verify()

        self.assertEqual(response.status_code, 400)

    def test_a_code_cannot_be_spent_twice(self, _):
        self._request()
        self._verify()

        self.user.phone_number = OTHER_NUMBER
        self.user.save(update_fields=["phone_number"])

        response = self._verify()

        self.assertEqual(response.status_code, 400)

    def test_a_number_held_by_another_account_is_refused(self, _):
        UserFactory(phone_number=NUMBER)

        response = self._request()

        self.assertEqual(response.status_code, 400)
        self.assertIn("phone_number", response.json()["errors"])
        self.assertFalse(OTP.objects.filter(user=self.user).exists())

    def test_a_number_taken_between_request_and_verify_is_refused(self, _):
        self._request()
        UserFactory(phone_number=NUMBER)

        response = self._verify()

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.phone_number)

    def test_the_current_number_is_refused(self, _):
        self.user.phone_number = NUMBER
        self.user.save(update_fields=["phone_number"])

        response = self._request()

        self.assertEqual(response.status_code, 400)

    def test_an_invalid_number_is_refused(self, _):
        response = self._request("not-a-number")

        self.assertEqual(response.status_code, 400)

    def test_requests_are_throttled(self, _):
        self._request()

        response = self._request()

        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)

    def test_resend_otp_refuses_a_phone_change_code(self, _):
        response = APIClient().post(
            "/api/v1/auth/resend-otp",
            {"email": self.user.email, "purpose": OTPPurpose.PHONE_CHANGE},
        )

        self.assertEqual(response.status_code, 400)

    def test_both_calls_need_a_session(self, _):
        anonymous = APIClient()

        self.assertEqual(
            anonymous.post(REQUEST_URL, {"phone_number": NUMBER}).status_code,
            401,
        )
        self.assertEqual(
            anonymous.post(
                VERIFY_URL, {"phone_number": NUMBER, "otp": CODE}
            ).status_code,
            401,
        )
