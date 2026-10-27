"""Two-step verification: setup, sign-in, recovery codes, turning it off."""

import base64
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.authentication.models import MFADevice, MFARecoveryCode
from apps.authentication.utils import totp
from apps.vendors.factories import UserFactory

PASSWORD = "Str0ng!Passphrase1"


def code_for(secret, offset=0):
    return totp.code_at(secret, totp.current_step() + offset)


class MFATestCase(TestCase):

    def setUp(self):
        cache.clear()
        self.user = UserFactory(is_active=True, is_verified=True)
        self.user.set_password(PASSWORD)
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def enable(self):
        secret = self.client.post("/api/v1/auth/mfa/setup").data["data"]["secret"]
        codes = self.client.post(
            "/api/v1/auth/mfa/confirm",
            {"code": code_for(secret)},
            format="json",
        ).data["data"]["recovery_codes"]
        # The confirm code's step is spent; the next sign-in needs a newer one.
        self.secret = secret

        return codes

    def sign_in(self):
        return APIClient().post(
            "/api/v1/auth/login",
            {"email": self.user.email, "password": PASSWORD},
            format="json",
        ).json()["data"]

    def finish(self, mfa_token, code):
        return APIClient().post(
            "/api/v1/auth/login/mfa",
            {"mfa_token": mfa_token, "code": code},
            format="json",
        )


class TotpTests(TestCase):

    def test_rfc_6238_vectors(self):
        secret = base64.b32encode(b"12345678901234567890").decode()

        self.assertEqual(totp.code_at(secret, 59 // 30), "287082")
        self.assertEqual(totp.code_at(secret, 1111111109 // 30), "081804")

    def test_a_code_from_the_previous_step_still_counts(self):
        secret = totp.new_secret()

        self.assertIsNotNone(totp.matching_step(secret, code_for(secret, -1)))
        self.assertIsNone(totp.matching_step(secret, code_for(secret, -3)))

    def test_the_uri_names_swayp_and_the_account(self):
        uri = totp.provisioning_uri("ABC", "sam@example.com")

        self.assertTrue(uri.startswith("otpauth://totp/Swayp%3Asam%40example.com?"))
        self.assertIn("issuer=Swayp", uri)


class SetupTests(MFATestCase):

    def test_off_by_default(self):
        data = self.client.get("/api/v1/auth/mfa").data["data"]

        self.assertEqual(
            data,
            {"enabled": False, "enabled_at": None, "recovery_codes_remaining": 0},
        )

    def test_setup_alone_changes_nothing(self):
        self.client.post("/api/v1/auth/mfa/setup")

        self.assertFalse(self.client.get("/api/v1/auth/mfa").data["data"]["enabled"])
        self.assertFalse(self.sign_in()["mfa_required"])

    def test_the_secret_is_encrypted_at_rest(self):
        secret = self.client.post("/api/v1/auth/mfa/setup").data["data"]["secret"]

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT secret FROM mfa_devices")
            stored = cursor.fetchone()[0]

        self.assertNotEqual(stored, secret)

    def test_confirming_turns_it_on_and_returns_ten_codes(self):
        codes = self.enable()

        self.assertEqual(len(codes), 10)
        status = self.client.get("/api/v1/auth/mfa").data["data"]
        self.assertTrue(status["enabled"])
        self.assertEqual(status["recovery_codes_remaining"], 10)

    def test_a_wrong_confirm_code_is_refused(self):
        self.client.post("/api/v1/auth/mfa/setup")

        response = self.client.post(
            "/api/v1/auth/mfa/confirm", {"code": "000000"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "mfa_code_invalid")

    def test_setup_is_refused_while_on(self):
        self.enable()

        response = self.client.post("/api/v1/auth/mfa/setup")

        self.assertEqual(response.data["code"], "mfa_already_enabled")


class SignInTests(MFATestCase):

    def test_without_mfa_sign_in_returns_tokens(self):
        data = self.sign_in()

        self.assertFalse(data["mfa_required"])
        self.assertIsNotNone(data["access"])
        self.assertIsNone(data["mfa_token"])

    def test_with_mfa_sign_in_returns_a_challenge_and_no_tokens(self):
        self.enable()

        data = self.sign_in()

        self.assertTrue(data["mfa_required"])
        self.assertIsNone(data["access"])
        self.assertIsNone(data["refresh"])
        self.assertEqual(data["mfa_methods"], ["totp", "recovery_code"])

    def test_an_app_code_finishes_the_sign_in(self):
        self.enable()

        response = self.finish(self.sign_in()["mfa_token"], code_for(self.secret, 1))

        self.assertEqual(response.status_code, 200, response.data)
        data = response.json()["data"]
        self.assertEqual(data["mfa_method"], "totp")

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['access']}")
        self.assertEqual(client.get("/api/v1/users/profile").status_code, 200)

    def test_an_app_code_works_once(self):
        self.enable()
        code = code_for(self.secret, 1)
        self.finish(self.sign_in()["mfa_token"], code)

        response = self.finish(self.sign_in()["mfa_token"], code)

        self.assertEqual(response.data["code"], "mfa_code_invalid")

    def test_a_challenge_works_once(self):
        self.enable()
        token = self.sign_in()["mfa_token"]
        self.finish(token, code_for(self.secret, 1))

        response = self.finish(token, code_for(self.secret, 0))

        self.assertEqual(response.data["code"], "mfa_challenge_invalid")

    def test_five_wrong_codes_end_the_challenge(self):
        self.enable()
        token = self.sign_in()["mfa_token"]

        for _ in range(5):
            self.finish(token, "000000")

        response = self.finish(token, code_for(self.secret, 1))

        self.assertEqual(response.data["code"], "mfa_challenge_invalid")

    def test_ten_wrong_codes_pause_two_step_sign_in_for_the_user(self):
        self.enable()

        for _ in range(2):
            token = self.sign_in()["mfa_token"]
            for _ in range(5):
                self.finish(token, "000000")

        response = self.finish(self.sign_in()["mfa_token"], code_for(self.secret, 1))

        self.assertEqual(response.data["code"], "account_locked")

    def test_a_forged_challenge_is_refused(self):
        response = self.finish("not-a-challenge", "123456")

        self.assertEqual(response.data["code"], "mfa_challenge_invalid")

    def test_a_recovery_code_works_once_and_emails_the_user(self):
        codes = self.enable()

        with mock.patch(
            "apps.authentication.services.mfa_service.notify"
        ) as notify:
            response = self.finish(self.sign_in()["mfa_token"], codes[0].upper())

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()["data"]["mfa_method"], "recovery_code")
        notify.assert_called_once_with(self.user, "MFA_RECOVERY_CODE_USED")

        again = self.finish(self.sign_in()["mfa_token"], codes[0])
        self.assertEqual(again.data["code"], "mfa_code_invalid")

    def test_phone_and_google_sign_in_take_the_same_step(self):
        """Every sign-in path answers through LoginService.sign_in."""
        from apps.authentication.services.login_service import LoginService

        self.enable()

        self.assertTrue(LoginService.sign_in(self.user, None)["mfa_required"])


class ManageTests(MFATestCase):

    def test_new_recovery_codes_void_the_old_ones(self):
        old = self.enable()

        new = self.client.post(
            "/api/v1/auth/mfa/recovery-codes",
            {"code": code_for(self.secret, 1)},
            format="json",
        ).data["data"]["recovery_codes"]

        self.assertEqual(len(new), 10)
        self.assertNotEqual(set(old), set(new))
        response = self.finish(self.sign_in()["mfa_token"], old[0])
        self.assertEqual(response.data["code"], "mfa_code_invalid")

    def test_new_recovery_codes_need_an_app_code(self):
        codes = self.enable()

        response = self.client.post(
            "/api/v1/auth/mfa/recovery-codes", {"code": codes[0]}, format="json"
        )

        self.assertEqual(response.data["code"], "mfa_code_invalid")

    def test_turning_it_off_needs_the_password(self):
        self.enable()

        response = self.client.post(
            "/api/v1/auth/mfa/disable",
            {"code": code_for(self.secret, 1), "password": "wrong"},
            format="json",
        )

        self.assertEqual(response.data["code"], "invalid_credentials")
        self.assertTrue(MFADevice.objects.filter(user=self.user).exists())

    def test_turning_it_off_signs_other_devices_out(self):
        codes = self.enable()
        other = self.finish(self.sign_in()["mfa_token"], code_for(self.secret, 1))
        other_access = other.json()["data"]["access"]

        response = self.client.post(
            "/api/v1/auth/mfa/disable",
            {"code": codes[1], "password": PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(MFADevice.objects.filter(user=self.user).exists())
        self.assertFalse(MFARecoveryCode.objects.filter(user=self.user).exists())

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {other_access}")
        self.assertEqual(client.get("/api/v1/users/profile").status_code, 401)
        self.assertFalse(self.sign_in()["mfa_required"])

    def test_a_google_only_account_turns_it_off_with_a_code_alone(self):
        self.user.set_unusable_password()
        self.user.save()
        self.enable()

        response = self.client.post(
            "/api/v1/auth/mfa/disable",
            {"code": code_for(self.secret, 1)},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
