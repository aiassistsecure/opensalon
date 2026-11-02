"""Accounts: email + PIN sign-in (founder's KISS spec, 2026-11-02).

Email says who you are, the time-clock PIN is the key — no
passwords, 2FA later. The desk keeps working signed-out; an
account is a new door. These tests pin the door's shape: who
gets in, who doesn't, and the manager's email admin on the
Team page.
"""

from django.test import TestCase
from django.urls import reverse

from saloncore.models import Salon
from team.models import StaffMember


class SignInTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Signin Salon", timezone="UTC")
        self.member = StaffMember.objects.create(
            salon=self.salon, display_name="Dana",
            email="dana@salon.test", pin="2468",
        )

    def test_signin_page_renders(self):
        response = self.client.get(reverse("webui:sign_in"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in")

    def test_email_and_pin_sign_in(self):
        response = self.client.post(
            reverse("webui:sign_in"),
            {"email": "Dana@Salon.Test", "pin": "2468"},
        )
        self.assertRedirects(
            response, reverse("webui:my_day"), fetch_redirect_response=False
        )
        self.assertEqual(
            self.client.session.get("staff_member_id"), self.member.pk
        )

    def test_wrong_pin_stays_out(self):
        response = self.client.post(
            reverse("webui:sign_in"),
            {"email": "dana@salon.test", "pin": "9999"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "match an account")
        self.assertIsNone(self.client.session.get("staff_member_id"))

    def test_unknown_email_stays_out(self):
        response = self.client.post(
            reverse("webui:sign_in"),
            {"email": "nobody@salon.test", "pin": "2468"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.session.get("staff_member_id"))

    def test_member_without_pin_cannot_sign_in(self):
        StaffMember.objects.create(
            salon=self.salon, display_name="NoPin",
            email="nopin@salon.test", pin="",
        )
        response = self.client.post(
            reverse("webui:sign_in"),
            {"email": "nopin@salon.test", "pin": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.session.get("staff_member_id"))

    def test_inactive_member_stays_out(self):
        StaffMember.objects.create(
            salon=self.salon, display_name="Gone",
            email="gone@salon.test", pin="1357", active=False,
        )
        response = self.client.post(
            reverse("webui:sign_in"),
            {"email": "gone@salon.test", "pin": "1357"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.session.get("staff_member_id"))

    def test_sign_out_clears_the_account(self):
        self.client.post(
            reverse("webui:sign_in"),
            {"email": "dana@salon.test", "pin": "2468"},
        )
        self.assertIsNotNone(self.client.session.get("staff_member_id"))
        self.client.get(reverse("webui:sign_out"))
        self.assertIsNone(self.client.session.get("staff_member_id"))


class TeamEmailAdminTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Admin Salon", timezone="UTC")
        self.member = StaffMember.objects.create(
            salon=self.salon, display_name="Dana", pin="2468"
        )

    def _post(self, **data):
        return self.client.post(reverse("webui:team"), data)

    def test_manager_sets_and_clears_account_email(self):
        self._post(
            action="set_email", member=self.member.pk,
            email="dana@salon.test",
        )
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, "dana@salon.test")
        self._post(action="set_email", member=self.member.pk, email="")
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, "")

    def test_one_email_names_one_account(self):
        StaffMember.objects.create(
            salon=self.salon, display_name="Bea",
            email="shared@salon.test", pin="1111",
        )
        response = self._post(
            action="set_email", member=self.member.pk,
            email="shared@salon.test",
        )
        self.assertContains(response, "already Bea")
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, "")
