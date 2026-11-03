"""Adding a stylist from the Team & Roster page.

Until the page grew this card, a new person could only arrive by
import — the manager had no door to create one, though the same
page already edited everyone's PIN, email, and services. The
card creates the StaffMember in one post: the name is required;
level, email, and PIN are optional, each validated with the same
rules the rest of the page enforces — an email names one account,
a PIN is 4 to 8 digits and unique in the salon.
"""

from django.test import Client, TestCase
from django.urls import reverse

from saloncore.models import Salon, StaffLevel
from team.models import StaffMember


class AddMemberTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.salon = Salon.objects.create(
            name="Mint", timezone="America/New_York"
        )
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Artist Level 1"
        )
        self.dawn = StaffMember.objects.create(
            salon=self.salon,
            display_name="Dawn Davalos",
            email="dawn@example.com",
            pin="101985",
        )
        self.team_url = reverse("webui:team")

    def add(self, **fields):
        data = {"action": "add_member"}
        data.update(fields)
        return self.client.post(self.team_url, data=data)

    def test_page_offers_the_card_and_the_levels(self):
        response = self.client.get(self.team_url)
        self.assertContains(response, "Add a stylist")
        self.assertContains(response, "Artist Level 1")

    def test_creates_member_with_everything(self):
        response = self.add(
            display_name="New Person",
            level=str(self.level.pk),
            email="new@example.com",
            pin="246810",
        )
        member = StaffMember.objects.get(display_name="New Person")
        self.assertEqual(member.salon, self.salon)
        self.assertEqual(member.staff_level, self.level)
        self.assertEqual(member.email, "new@example.com")
        self.assertEqual(member.pin, "246810")
        self.assertTrue(member.active)
        self.assertContains(response, "New Person is on the team")

    def test_name_only_creates_a_member_without_an_account(self):
        self.add(display_name="Just A Name")
        member = StaffMember.objects.get(display_name="Just A Name")
        self.assertIsNone(member.staff_level)
        self.assertEqual(member.email, "")
        self.assertEqual(member.pin, "")

    def test_blank_name_creates_nothing(self):
        response = self.add(display_name="   ", pin="246810")
        self.assertEqual(StaffMember.objects.count(), 1)
        self.assertContains(response, "needs a name")

    def test_bad_email_creates_nothing(self):
        response = self.add(display_name="New Person", email="not-an-email")
        self.assertEqual(StaffMember.objects.count(), 1)
        self.assertContains(response, "look like an email")

    def test_duplicate_email_creates_nothing(self):
        response = self.add(
            display_name="New Person", email="DAWN@example.com"
        )
        self.assertEqual(StaffMember.objects.count(), 1)
        self.assertContains(response, "already Dawn Davalos")

    def test_short_pin_creates_nothing(self):
        response = self.add(display_name="New Person", pin="123")
        self.assertEqual(StaffMember.objects.count(), 1)
        self.assertContains(response, "4 to 8 digits")

    def test_duplicate_pin_creates_nothing(self):
        response = self.add(display_name="New Person", pin="101985")
        self.assertEqual(StaffMember.objects.count(), 1)
        self.assertContains(response, "already Dawn Davalos")

    def test_unknown_level_is_ignored_not_fatal(self):
        self.add(display_name="New Person", level="99999")
        member = StaffMember.objects.get(display_name="New Person")
        self.assertIsNone(member.staff_level)

    def test_new_member_appears_on_the_page(self):
        response = self.add(display_name="New Person")
        self.assertContains(response, "New Person")
