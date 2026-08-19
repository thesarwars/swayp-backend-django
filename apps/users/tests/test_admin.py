"""The users models are reachable in the admin, and the password survives it.

The load-bearing test is the last one. A custom user model registered with a
plain ModelAdmin renders ``password`` as an ordinary text input holding the
stored hash: opening a user and pressing Save writes that hash back as the
literal new password, and the account can no longer be logged into. It fails
silently and it fails on a page an operator has every reason to visit, so it is
asserted against behaviour rather than against which base class is in use.
"""

from django.contrib import admin
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.users.admin import BusinessProfileInline, IndividualProfileInline
from apps.users.models import (
    AccountType,
    BusinessProfile,
    IndividualProfile,
    Profile,
    User,
)

PASSWORD = "Str0ng!Passphrase1"


class UsersAdminTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_superuser(
            email="root@acme.com", password=PASSWORD
        )

        cls.business = Profile.objects.create(
            user=cls.staff,
            account_type=AccountType.BUSINESS,
            full_name="Jane Smith",
        )
        BusinessProfile.objects.create(
            profile=cls.business,
            business_name="Acme Corporation, LLC",
            poc_name="Jane Smith",
        )

        cls.individual_user = User.objects.create_user(
            email="sole@acme.com", password=PASSWORD
        )
        cls.individual = Profile.objects.create(
            user=cls.individual_user,
            account_type=AccountType.INDIVIDUAL,
            full_name="Dana Reed",
        )
        IndividualProfile.objects.create(profile=cls.individual)

    def setUp(self):
        self.client.force_login(self.staff)

    def as_staff(self):
        """ModelAdmin hooks read request.user, so None will not do."""
        request = RequestFactory().get("/admin/")
        request.user = self.staff

        return request

    def url(self, model, view, *args):
        meta = model._meta

        return reverse(
            f"admin:{meta.app_label}_{meta.model_name}_{view}", args=args
        )

    def test_every_model_in_the_app_is_registered(self):
        registered = set(admin.site._registry)

        for model in (User, Profile, BusinessProfile, IndividualProfile):
            with self.subTest(model=model.__name__):
                self.assertIn(model, registered)

    def test_every_page_renders(self):
        pages = [
            (User, "changelist", ()),
            (User, "add", ()),
            (User, "change", (self.staff.pk,)),
            (Profile, "changelist", ()),
            (Profile, "change", (self.business.pk,)),
            (BusinessProfile, "changelist", ()),
            (IndividualProfile, "changelist", ()),
        ]

        for model, view, args in pages:
            with self.subTest(model=model.__name__, view=view):
                response = self.client.get(self.url(model, view, *args))

                self.assertEqual(response.status_code, 200)

    def test_the_add_form_hashes_the_password_it_is_given(self):
        response = self.client.post(
            self.url(User, "add"),
            {
                "email": "new@acme.com",
                "usable_password": "true",
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )

        self.assertIn(response.status_code, (200, 302))

        created = User.objects.get(email="new@acme.com")

        self.assertNotEqual(created.password, PASSWORD)
        self.assertTrue(created.check_password(PASSWORD))

    def test_the_change_form_cannot_overwrite_the_password(self):
        """A ReadOnlyPasswordHashField is what makes Save non-destructive."""
        user_admin = admin.site._registry[User]
        form = user_admin.get_form(self.as_staff(), obj=self.staff)()

        self.assertIsInstance(
            form.fields["password"], ReadOnlyPasswordHashField
        )

    def test_the_change_page_does_not_render_the_hash(self):
        body = self.client.get(
            self.url(User, "change", self.staff.pk)
        ).content.decode()

        self.assertNotIn(self.staff.password, body)

    def test_only_the_matching_sub_profile_is_offered(self):
        """A blank business form on an individual account invites a bad row."""
        profile_admin = admin.site._registry[Profile]

        request = self.as_staff()

        self.assertEqual(
            profile_admin.get_inlines(request, self.business),
            [BusinessProfileInline],
        )
        self.assertEqual(
            profile_admin.get_inlines(request, self.individual),
            [IndividualProfileInline],
        )
