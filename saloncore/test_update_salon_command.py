"""Tests for the update_salon management command. Synthetic only."""
import io

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon


class UpdateSalonCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Example Salon", timezone="UTC", currency="USD",
            tagline="Old", primary_color="#112233")

    def fresh(self):
        return Salon.objects.get(pk=self.salon.pk)

    def _run(self, **kwargs):
        out = io.StringIO()
        call_command("update_salon", stdout=out, **kwargs)
        return out.getvalue()

    def test_real_run_updates_and_reports_fields(self):
        text = self._run(
            salon_id=self.salon.id, name="New Name",
            timezone="America/New_York", currency="eur")
        fresh = self.fresh()
        self.assertEqual(
            (fresh.name, fresh.timezone, fresh.currency),
            ("New Name", "America/New_York", "EUR"))
        self.assertIn("set name", text)
        self.assertIn("set currency", text)
        self.assertEqual(fresh.tagline, "Old")

    def test_partial_and_clearing_via_argv(self):
        out = io.StringIO()
        call_command(
            "update_salon", "--salon-id", str(self.salon.id),
            "--tagline", "", "--primary-color", "#AABBCC",
            stdout=out)
        fresh = self.fresh()
        self.assertEqual(
            (fresh.tagline, fresh.primary_color, fresh.name),
            ("", "#AABBCC", "Example Salon"))

    def test_no_change_reports_no_changes(self):
        text = self._run(salon_id=self.salon.id, name="Example Salon")
        self.assertIn("no changes", text)

    def test_dry_run_previews_and_writes_nothing(self):
        text = self._run(
            salon_id=self.salon.id, name="New Name",
            accent_color="#000000", dry_run=True)
        self.assertIn("would set name", text)
        self.assertIn("would set accent_color", text)
        fresh = self.fresh()
        self.assertEqual((fresh.name, fresh.accent_color),
                         ("Example Salon", ""))

    def test_no_fields_refused(self):
        with self.assertRaises(CommandError):
            self._run(salon_id=self.salon.id)
        with self.assertRaises(CommandError):
            self._run(salon_id=self.salon.id, dry_run=True)

    def test_invalid_values_write_nothing(self):
        for kwargs in ({"timezone": "Bogus/Zone"},
                       {"primary_color": "red"},
                       {"logo_url": "not a url"}):
            with self.assertRaises(CommandError, msg=str(kwargs)):
                self._run(salon_id=self.salon.id, **kwargs)
        fresh = self.fresh()
        self.assertEqual(
            (fresh.timezone, fresh.primary_color, fresh.logo_url),
            ("UTC", "#112233", ""))

    def test_unknown_salon_refused(self):
        with self.assertRaises(CommandError):
            self._run(salon_id=999999, name="New")
