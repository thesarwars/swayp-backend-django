"""Failed-login lockout (E2).

``failed_login_attempts`` and ``locked_until`` sat on the User model from the
first migration with nothing reading or writing them, so password guessing was
unbounded while the schema looked like it was protected. Fields without a
caller are not a feature.
"""

import datetime as dt

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.services.lockout_service import LockoutService
from apps.users.models.user import User
from apps.vendors.factories import UserFactory

URL = "/api/v1/auth/login/"
PASSWORD = "Str0ng!Passphrase1"


def make_user(**kwargs):
    user = UserFactory(**kwargs)
    user.set_password(PASSWORD)
    user.is_active = True
    user.is_verified = True
    user.save()

    return user


@override_settings(LOGIN_MAX_ATTEMPTS=3, LOGIN_LOCKOUT_MINUTES=15)
class LoginLockoutTests(TestCase):

    def setUp(self):
        self.user = make_user(email="target@example.com")
        self.client = APIClient()

    def attempt(self, password):
        return self.client.post(
            URL, {"email": self.user.email, "password": password},
            format="json",
        )

    def test_a_wrong_password_is_counted(self):
        self.attempt("wrong")
        self.user.refresh_from_db()

        self.assertEqual(self.user.failed_login_attempts, 1)

    def test_the_account_locks_at_the_ceiling(self):
        for _ in range(3):
            self.attempt("wrong")

        self.user.refresh_from_db()

        self.assertIsNotNone(self.user.locked_until)
        self.assertTrue(LockoutService().is_locked(self.user))

    def test_a_locked_account_is_refused_even_with_the_right_password(self):
        """The lock is on the account, not on the password check."""
        for _ in range(3):
            self.attempt("wrong")

        response = self.attempt(PASSWORD)

        self.assertEqual(response.status_code, 400)

    def test_the_message_says_how_long(self):
        """"Invalid email or password" would leave someone who mistyped twice
        guessing why their correct password stopped working."""
        for _ in range(3):
            self.attempt("wrong")

        body = str(self.attempt(PASSWORD).data)

        self.assertIn("Too many failed attempts", body)
        self.assertIn("minute", body)

    def test_a_correct_password_clears_the_counter(self):
        self.attempt("wrong")
        self.attempt("wrong")
        self.attempt(PASSWORD)

        self.user.refresh_from_db()

        self.assertEqual(self.user.failed_login_attempts, 0)

    def test_the_lock_expires(self):
        for _ in range(3):
            self.attempt("wrong")

        self.user.refresh_from_db()
        self.user.locked_until = timezone.now() - dt.timedelta(minutes=1)
        self.user.save(update_fields=["locked_until"])

        self.assertEqual(self.attempt(PASSWORD).status_code, 200)

    def test_a_successful_login_clears_a_stale_lock(self):
        self.user.failed_login_attempts = 2
        self.user.locked_until = timezone.now() - dt.timedelta(hours=1)
        self.user.save()

        self.attempt(PASSWORD)
        self.user.refresh_from_db()

        self.assertIsNone(self.user.locked_until)
        self.assertEqual(self.user.failed_login_attempts, 0)


@override_settings(LOGIN_MAX_ATTEMPTS=3)
class LockoutDoesNotLeakTests(TestCase):
    """A lockout must not become a way to discover who has an account."""

    def setUp(self):
        self.client = APIClient()

    def test_an_unknown_email_creates_nothing(self):
        for _ in range(5):
            self.client.post(
                URL, {"email": "ghost@example.com", "password": "wrong"},
                format="json",
            )

        self.assertFalse(User.objects.filter(email="ghost@example.com"))

    def test_unknown_and_wrong_password_answer_the_same(self):
        known = make_user(email="known@example.com")

        unknown = self.client.post(
            URL, {"email": "ghost@example.com", "password": "wrong"},
            format="json",
        )
        wrong = self.client.post(
            URL, {"email": known.email, "password": "wrong"}, format="json",
        )

        self.assertEqual(unknown.status_code, wrong.status_code)
        self.assertEqual(str(unknown.data), str(wrong.data))

    def test_one_accounts_lock_does_not_affect_another(self):
        victim = make_user(email="victim@example.com")
        bystander = make_user(email="bystander@example.com")

        for _ in range(3):
            self.client.post(
                URL, {"email": victim.email, "password": "wrong"},
                format="json",
            )

        response = self.client.post(
            URL, {"email": bystander.email, "password": PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 200)


class LockoutServiceTests(TestCase):

    def setUp(self):
        self.service = LockoutService()

    def test_an_unlocked_user_reports_no_remaining_time(self):
        self.assertEqual(
            self.service.minutes_remaining(UserFactory()), 0
        )

    def test_remaining_minutes_round_up(self):
        """"Try again in 0 minutes" is not an instruction."""
        user = UserFactory()
        user.locked_until = timezone.now() + dt.timedelta(seconds=30)

        self.assertGreaterEqual(self.service.minutes_remaining(user), 1)

    def test_none_is_handled_everywhere(self):
        self.assertFalse(self.service.is_locked(None))
        self.assertIsNone(self.service.record_failure(None))
        self.assertIsNone(self.service.record_success(None))
