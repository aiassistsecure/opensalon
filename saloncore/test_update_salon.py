"""Tests for saloncore.update_salon. Synthetic fixtures only."""
from django.test import TestCase

from saloncore.models import Salon
from saloncore.update_salon import update_salon, validate_update_salon


class UpdateSalonTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Example Salon", timezone="UTC", currency="USD",
            tagline="Old tagline", logo_url="https://example.com/a.png",
            primary_color="#112233", accent_color="#445566")

    def fresh(self):
        return Salon.objects.get(pk=self.salon.pk)

    def snapshot(self):
        s = self.fresh()
        return (s.name, s.timezone, s.currency, s.tagline, s.logo_url,
                s.primary_color, s.accent_color)  # full field tuple

    def test_partial_update_only_named_fields(self):
        result = update_salon(self.salon, name="  New Name  ")
        self.assertTrue(result.changed)
        self.assertEqual(result.changed_fields, ("name",))
        self.assertEqual(result.changes[0].old_value, "Example Salon")
        self.assertIsNotNone(result.changed_at)
        fresh = self.fresh()
        self.assertEqual(fresh.name, "New Name")
        self.assertEqual(
            (fresh.timezone, fresh.currency, fresh.tagline),
            ("UTC", "USD", "Old tagline"))

    def test_all_fields_and_currency_uppercased(self):
        result = update_salon(
            self.salon, name="New", timezone="America/New_York",
            currency="eur", tagline="Fresh",
            logo_url="https://example.com/b.png",
            primary_color="#AABBCC", accent_color="#ddeeff")
        self.assertEqual(result.changed_fields, (
            "name", "timezone", "currency", "tagline", "logo_url",
            "primary_color", "accent_color"))
        self.assertEqual(self.snapshot(), (
            "New", "America/New_York", "EUR", "Fresh",
            "https://example.com/b.png", "#AABBCC", "#ddeeff"))

    def test_clearing_branding_fields_with_empty_string(self):
        update_salon(self.salon, tagline="", logo_url="",
                     primary_color="", accent_color="")
        self.assertEqual(self.snapshot()[3:], ("", "", "", ""))

    def test_no_change_saves_nothing(self):
        result = update_salon(self.salon, name="Example Salon")
        self.assertFalse(result.changed)
        self.assertEqual(result.changed_fields, ())
        self.assertIsNone(result.changed_at)

    def test_no_fields_refused(self):
        with self.assertRaises(ValueError):
            update_salon(self.salon)
        with self.assertRaises(ValueError):
            validate_update_salon(self.salon)

    def test_invalid_values_write_nothing(self):
        before = self.snapshot()
        cases = (
            {"name": "   "}, {"name": "x" * 201}, {"name": 123},
            {"timezone": "Not/AZone"}, {"timezone": ""},
            {"timezone": "x" * 65},
            {"currency": "US"}, {"currency": "USDD"},
            {"currency": "U1D"}, {"currency": 123},
            {"tagline": "x" * 201}, {"tagline": 5},
            {"logo_url": "not a url"}, {"logo_url": "x" * 501},
            {"primary_color": "112233"}, {"primary_color": "#12345"},
            {"primary_color": "#GGGGGG"}, {"accent_color": "red"},
        )
        for kwargs in cases:
            with self.assertRaises(ValueError, msg=str(kwargs)):
                update_salon(self.salon, **kwargs)
        self.assertEqual(self.snapshot(), before)

    def test_unsaved_salon_refused(self):
        with self.assertRaises(ValueError):
            update_salon(Salon(name="Unsaved"), name="New")

    def test_validate_writes_nothing_and_cleans(self):
        before = self.snapshot()
        cleaned = validate_update_salon(
            self.salon, currency="gbp", name="  Padded  ")
        self.assertEqual(cleaned["currency"], "GBP")
        self.assertEqual(cleaned["name"], "Padded")
        self.assertNotIn("tagline", cleaned)
        self.assertEqual(self.snapshot(), before)

    def test_only_changed_fields_written(self):
        # An unrelated in-memory edit must not be persisted when
        # only one field is saved via update_fields.
        self.salon.tagline = "Unsaved in-memory edit"
        update_salon(self.salon, name="Renamed")
        fresh = self.fresh()
        self.assertEqual(fresh.name, "Renamed")
        self.assertEqual(fresh.tagline, "Old tagline")
