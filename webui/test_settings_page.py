"""Settings page — the salon profile and the box's state.

Pins: the page shows the Salon record itself; saving validates
the whole profile or changes nothing (a real IANA zone, a
three-letter currency, a non-empty name); the system card
reports presence — engine, mail host, adapter — never values
it shouldn't carry.
"""
from django.test import TestCase
from django.urls import reverse

from saloncore.models import Salon


class SettingsPageTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Old Name", timezone="UTC", currency="USD"
        )

    def test_page_shows_profile_and_box_state(self):
        response = self.client.get(reverse("webui:settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Old Name")
        # The test run is the SQLite fallback, and the card says so.
        self.assertEqual(response.context["db_label"], "SQLite")
        self.assertEqual(response.context["sms_adapter"], "ConsoleSmsAdapter")
        self.assertEqual(response.context["staff_count"], 0)

    def test_save_updates_the_whole_profile(self):
        response = self.client.post(
            reverse("webui:settings_save"),
            {
                "name": "New Name Salon",
                "timezone": "America/New_York",
                "currency": "usd",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("saved=1", response.url)
        self.salon.refresh_from_db()
        self.assertEqual(self.salon.name, "New Name Salon")
        self.assertEqual(self.salon.timezone, "America/New_York")
        self.assertEqual(self.salon.currency, "USD")

    def test_bad_timezone_saves_nothing(self):
        response = self.client.post(
            reverse("webui:settings_save"),
            {"name": "New Name", "timezone": "Not/AZone", "currency": "EUR"},
        )
        self.assertIn("error=timezone", response.url)
        self.salon.refresh_from_db()
        self.assertEqual(self.salon.name, "Old Name")
        self.assertEqual(self.salon.currency, "USD")

    def test_bad_currency_and_empty_name_save_nothing(self):
        response = self.client.post(
            reverse("webui:settings_save"),
            {"name": "Fine", "timezone": "UTC", "currency": "USDD"},
        )
        self.assertIn("error=currency", response.url)
        response = self.client.post(
            reverse("webui:settings_save"),
            {"name": "   ", "timezone": "UTC", "currency": "USD"},
        )
        self.assertIn("error=name", response.url)
        self.salon.refresh_from_db()
        self.assertEqual(self.salon.name, "Old Name")

    def test_save_is_post_only(self):
        response = self.client.get(reverse("webui:settings_save"))
        self.assertEqual(response.status_code, 405)
