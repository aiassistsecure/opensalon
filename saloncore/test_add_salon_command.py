"""Tests for the add_salon management command. Synthetic only."""
import io

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon


class AddSalonCommandTests(TestCase):
    def run_cmd(self, **kwargs):
        out = io.StringIO()
        call_command("add_salon", stdout=out, **kwargs)
        return out.getvalue()

    def test_happy_path_defaults(self):
        text = self.run_cmd(name="Example Salon")
        (s,) = Salon.objects.all()
        self.assertEqual(
            (s.name, s.timezone, s.currency, s.tagline, s.logo_url,
             s.primary_color, s.accent_color),
            ("Example Salon", "UTC", "USD", "", "", "", ""))
        self.assertIn(f"Created salon {s.pk}", text)
        self.assertIn("Example Salon", text)

    def test_flag_form_full_branding(self):
        out = io.StringIO()
        call_command(
            "add_salon", "--name", "Mint",
            "--timezone", "America/New_York", "--currency", "eur",
            "--tagline", "Look great",
            "--logo-url", "https://example.com/logo.png",
            "--primary-color", "#112233",
            "--accent-color", "#445566", stdout=out)
        (s,) = Salon.objects.all()
        self.assertEqual(
            (s.name, s.timezone, s.currency, s.tagline, s.logo_url,
             s.primary_color, s.accent_color),
            ("Mint", "America/New_York", "EUR", "Look great",
             "https://example.com/logo.png", "#112233", "#445566"))
        self.assertIn("Created salon", out.getvalue())

    def test_dry_run_writes_nothing_and_previews(self):
        text = self.run_cmd(
            name="Example Salon", timezone="America/New_York",
            currency="EUR", dry_run=True)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertIn("Dry run: would create salon", text)
        self.assertIn("Example Salon", text)
        self.assertIn("America/New_York", text)
        self.assertIn("no salon written", text)

    def test_dry_run_invalid_writes_nothing(self):
        for kwargs in ({"name": "  "},
                       {"name": "Ok", "currency": "US"},
                       {"name": "Ok", "timezone": "Bogus/Zone"},
                       {"name": "Ok", "primary_color": "red"}):
            with self.assertRaises(CommandError, msg=str(kwargs)):
                self.run_cmd(dry_run=True, **kwargs)
        self.assertEqual(Salon.objects.count(), 0)

    def test_invalid_values_write_nothing(self):
        for kwargs in ({"name": "x" * 201},
                       {"name": "Ok", "currency": "USDD"},
                       {"name": "Ok", "timezone": "Not/AZone"},
                       {"name": "Ok", "logo_url": "not a url"}):
            with self.assertRaises(CommandError, msg=str(kwargs)):
                self.run_cmd(**kwargs)
        self.assertEqual(Salon.objects.count(), 0)
