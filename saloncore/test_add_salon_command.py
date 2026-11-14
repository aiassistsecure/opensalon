"""Tests for the add_salon management command. Synthetic only."""
import io
import json

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


class AddSalonCommandFormatTests(TestCase):
    def run_cmd(self, **kwargs):
        out = io.StringIO()
        call_command("add_salon", stdout=out, **kwargs)
        return out.getvalue()

    def test_default_text_output_unchanged(self):
        text = self.run_cmd(name="Example Salon")
        (s,) = Salon.objects.all()
        self.assertEqual(
            text,
            f"Created salon {s.pk}: 'Example Salon' "
            "timezone=UTC currency=USD tagline='' logo_url='' "
            "primary_color='' accent_color=''.\n")

    def test_default_text_dry_run_output_unchanged(self):
        text = self.run_cmd(name="Example Salon", dry_run=True)
        self.assertEqual(
            text,
            "Dry run: would create salon 'Example Salon': "
            "timezone=UTC currency=USD tagline='' logo_url='' "
            "primary_color='' accent_color='' "
            "-- no salon written.\n")
        self.assertEqual(Salon.objects.count(), 0)

    def test_explicit_text_format_matches_default(self):
        text = self.run_cmd(name="Example Salon", format="text")
        (s,) = Salon.objects.all()
        self.assertEqual(
            text,
            f"Created salon {s.pk}: 'Example Salon' "
            "timezone=UTC currency=USD tagline='' logo_url='' "
            "primary_color='' accent_color=''.\n")

    def test_json_output_parses_and_carries_facts(self):
        text = self.run_cmd(
            name="Example Salon", timezone="America/New_York",
            currency="EUR", tagline="Look great",
            logo_url="https://example.com/logo.png",
            primary_color="#112233", accent_color="#445566",
            format="json")
        (s,) = Salon.objects.all()
        self.assertNotIn("Created salon", text)
        self.assertEqual(json.loads(text), {
            "id": s.pk, "name": "Example Salon",
            "timezone": "America/New_York", "currency": "EUR",
            "tagline": "Look great",
            "logo_url": "https://example.com/logo.png",
            "primary_color": "#112233", "accent_color": "#445566",
            "dry_run": False})

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(
            "add_salon", "--name", "Mint", "--format", "json",
            stdout=out)
        row = json.loads(out.getvalue())
        (s,) = Salon.objects.all()
        self.assertEqual(
            (row["id"], row["name"], row["timezone"],
             row["dry_run"]),
            (s.pk, "Mint", "UTC", False))

    def test_dry_run_json_reports_dry_run_and_writes_nothing(self):
        text = self.run_cmd(
            name="Example Salon", timezone="America/New_York",
            dry_run=True, format="json")
        self.assertEqual(Salon.objects.count(), 0)
        self.assertNotIn("Dry run", text)
        row = json.loads(text)
        self.assertEqual(
            (row["id"], row["name"], row["timezone"],
             row["dry_run"]),
            (None, "Example Salon", "America/New_York", True))

    def test_json_invalid_writes_nothing_and_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_cmd(name="Ok", currency="US", format="json")
        self.assertEqual(Salon.objects.count(), 0)
