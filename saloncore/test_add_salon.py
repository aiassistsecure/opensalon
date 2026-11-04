"""Tests for saloncore.add_salon. Synthetic fixtures only."""
from django.test import TestCase

from saloncore.add_salon import add_salon, validate_add_salon
from saloncore.models import Salon


class AddSalonTests(TestCase):
    def test_creation_with_defaults(self):
        s = add_salon("  Example Salon  ")
        self.assertEqual(Salon.objects.count(), 1)
        self.assertEqual(
            (s.name, s.timezone, s.currency, s.tagline, s.logo_url,
             s.primary_color, s.accent_color),
            ("Example Salon", "UTC", "USD", "", "", "", ""))

    def test_creation_with_full_branding(self):
        s = add_salon(
            "Mint", timezone="America/New_York", currency="eur",
            tagline="  Look great  ",
            logo_url="https://example.com/logo.png",
            primary_color="#112233", accent_color="#ddeeff")
        self.assertEqual(
            (s.name, s.timezone, s.currency, s.tagline, s.logo_url,
             s.primary_color, s.accent_color),
            ("Mint", "America/New_York", "EUR", "Look great",
             "https://example.com/logo.png", "#112233", "#ddeeff"))

    def test_invalid_currency_rejected(self):
        for bad in ("US", "USDD", "U1D", "", 123):
            with self.assertRaises(ValueError, msg=repr(bad)):
                add_salon("Example", currency=bad)
        self.assertEqual(Salon.objects.count(), 0)

    def test_invalid_timezone_rejected(self):
        for bad in ("Not/AZone", "", "   ", "x" * 65, 123):
            with self.assertRaises(ValueError, msg=repr(bad)):
                add_salon("Example", timezone=bad)
        self.assertEqual(Salon.objects.count(), 0)

    def test_name_validation(self):
        for bad in ("", "   ", None, 123, "x" * 201):
            with self.assertRaises(ValueError, msg=repr(bad)):
                add_salon(bad)
        self.assertEqual(Salon.objects.count(), 0)
        s = add_salon("x" * 200)
        self.assertEqual(len(s.name), 200)

    def test_invalid_branding_rejected(self):
        cases = (
            {"tagline": "x" * 201}, {"tagline": 5},
            {"logo_url": "not a url"}, {"logo_url": "x" * 501},
            {"primary_color": "112233"}, {"primary_color": "#12345"},
            {"accent_color": "red"}, {"accent_color": "#GGGGGG"})
        for kwargs in cases:
            with self.assertRaises(ValueError, msg=str(kwargs)):
                add_salon("Example", **kwargs)
        self.assertEqual(Salon.objects.count(), 0)

    def test_validate_writes_nothing_and_cleans(self):
        cleaned = validate_add_salon("  Padded  ", currency="gbp")
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(
            (cleaned["name"], cleaned["timezone"],
             cleaned["currency"], cleaned["tagline"]),
            ("Padded", "UTC", "GBP", ""))

    def test_validate_same_errors_writes_nothing(self):
        for kwargs in ({"name": " "},
                       {"name": "Ok", "timezone": "Bogus/Zone"},
                       {"name": "Ok", "currency": "US"}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                validate_add_salon(**kwargs)
        self.assertEqual(Salon.objects.count(), 0)

    def test_none_optional_fields_use_defaults(self):
        s = add_salon("Example", timezone=None, currency=None,
                      tagline=None, logo_url=None,
                      primary_color=None, accent_color=None)
        self.assertEqual(
            (s.timezone, s.currency, s.tagline, s.logo_url,
             s.primary_color, s.accent_color),
            ("UTC", "USD", "", "", "", ""))
