"""Tests for the update_salon management command. Synthetic only."""
import io
import json

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


class UpdateSalonCommandFormatTests(TestCase):
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

    def test_default_text_output_unchanged(self):
        text = self._run(
            salon_id=self.salon.id, name="New Name", currency="eur")
        self.assertEqual(
            text,
            f"update_salon: salon_id={self.salon.id} set name\n"
            f"update_salon: salon_id={self.salon.id} set currency\n")

    def test_default_text_dry_run_output_unchanged(self):
        text = self._run(
            salon_id=self.salon.id, name="New Name", dry_run=True)
        self.assertEqual(
            text,
            f"update_salon dry-run: salon_id={self.salon.id} "
            "would set name\n")
        self.assertEqual(self.fresh().name, "Example Salon")

    def test_explicit_text_format_matches_default(self):
        text = self._run(
            salon_id=self.salon.id, name="New Name", format="text")
        self.assertEqual(
            text,
            f"update_salon: salon_id={self.salon.id} set name\n")

    def test_json_output_parses_and_carries_facts(self):
        text = self._run(
            salon_id=self.salon.id, name="New Name",
            timezone="America/New_York", currency="eur",
            format="json")
        fresh = self.fresh()
        self.assertEqual(
            (fresh.name, fresh.timezone, fresh.currency),
            ("New Name", "America/New_York", "EUR"))
        self.assertNotIn("update_salon:", text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertEqual(json.loads(text), {
            "salon_id": self.salon.id, "name": "New Name",
            "timezone": "America/New_York", "currency": "EUR",
            "tagline": "Old", "logo_url": "",
            "primary_color": "#112233", "accent_color": "",
            "changed_fields": ["name", "timezone", "currency"],
            "dry_run": False})

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(
            "update_salon", "--salon-id", str(self.salon.id),
            "--tagline", "Fresh", "--format", "json", stdout=out)
        row = json.loads(out.getvalue())
        self.assertEqual(
            (row["salon_id"], row["tagline"],
             row["changed_fields"], row["dry_run"]),
            (self.salon.id, "Fresh", ["tagline"], False))
        self.assertEqual(self.fresh().tagline, "Fresh")

    def test_json_no_changes(self):
        text = self._run(
            salon_id=self.salon.id, name="Example Salon",
            format="json")
        row = json.loads(text)
        self.assertEqual(
            (row["salon_id"], row["changed_fields"], row["dry_run"]),
            (self.salon.id, [], False))

    def test_dry_run_json_reports_dry_run_and_writes_nothing(self):
        text = self._run(
            salon_id=self.salon.id, name="New Name",
            accent_color="#000000", dry_run=True, format="json")
        fresh = self.fresh()
        self.assertEqual((fresh.name, fresh.accent_color),
                         ("Example Salon", ""))
        self.assertNotIn("dry-run", text)
        self.assertEqual(json.loads(text), {
            "salon_id": self.salon.id, "name": "New Name",
            "accent_color": "#000000",
            "changed_fields": ["name", "accent_color"],
            "dry_run": True})

    def test_dry_run_json_no_changes(self):
        text = self._run(
            salon_id=self.salon.id, name="Example Salon",
            dry_run=True, format="json")
        self.assertEqual(json.loads(text), {
            "salon_id": self.salon.id, "changed_fields": [],
            "dry_run": True})

    def test_json_errors_still_command_error(self):
        for kwargs in ({"timezone": "Bogus/Zone"},
                       {"primary_color": "red"}):
            with self.assertRaises(CommandError, msg=str(kwargs)):
                self._run(
                    salon_id=self.salon.id, format="json", **kwargs)
        with self.assertRaises(CommandError):
            self._run(salon_id=999999, name="New", format="json")
        with self.assertRaises(CommandError):
            self._run(
                salon_id=self.salon.id, name="New", format="bogus")
        fresh = self.fresh()
        self.assertEqual(
            (fresh.timezone, fresh.primary_color),
            ("UTC", "#112233"))
