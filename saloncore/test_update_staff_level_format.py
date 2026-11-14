import io
import json

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from saloncore.add_staff_level import add_staff_level
from saloncore.models import Salon, StaffLevel


class UpdateStaffLevelFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.level = add_staff_level(
            self.salon, "Level 6", sort_order=6, active=True)

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("staff_level_id", self.level.pk)
        call_command("update_staff_level", stdout=out, **kwargs)
        return out.getvalue()

    def stored(self):
        return StaffLevel.objects.get(pk=self.level.pk)

    def test_default_text_unchanged(self):
        text = self.run_cmd(name="Level 8", sort_order=8)
        self.assertEqual(
            text,
            f"Updated staff level {self.level.pk}: 'Level 8' "
            f"in salon {self.salon.pk}: sort_order=8 active=True.\n")
        self.assertEqual(self.stored().name, "Level 8")

    def test_explicit_text_format_matches_default(self):
        text = self.run_cmd(name="Level 8", sort_order=8, format="text")
        self.assertEqual(
            text,
            f"Updated staff level {self.level.pk}: 'Level 8' "
            f"in salon {self.salon.pk}: sort_order=8 active=True.\n")
        self.assertEqual(self.stored().name, "Level 8")

    def test_default_dry_run_text_unchanged(self):
        text = self.run_cmd(name="Level 8", sort_order=8, dry_run=True)
        self.assertIn("Dry run: would update staff level", text)
        self.assertIn("name='Level 8'", text)
        self.assertIn("sort_order=8", text)
        self.assertIn("no staff level written", text)
        self.assertEqual(self.stored().name, "Level 6")

    def test_json_output_parses_and_carries_facts(self):
        text = self.run_cmd(name="Level 8", sort_order=8, format="json")
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Level 8", 8, True))
        self.assertNotIn("Updated staff level", text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertEqual(json.loads(text), {
            "id": self.level.pk, "name": "Level 8",
            "salon_id": self.salon.pk, "sort_order": 8,
            "active": True, "dry_run": False})

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(
            "update_staff_level", "--salon-id", str(self.salon.pk),
            "--staff-level-id", str(self.level.pk),
            "--inactive", "--format", "json", stdout=out)
        row = json.loads(out.getvalue())
        self.assertEqual(
            (row["id"], row["salon_id"], row["active"],
             row["dry_run"]),
            (self.level.pk, self.salon.pk, False, False))
        self.assertFalse(self.stored().active)

    def test_dry_run_json_reports_dry_run_and_writes_nothing(self):
        text = self.run_cmd(
            name="Level 8", sort_order=8, dry_run=True, format="json")
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Level 6", 6, True))
        self.assertNotIn("Dry run", text)
        self.assertEqual(json.loads(text), {
            "id": self.level.pk, "salon_id": self.salon.pk,
            "name": "Level 8", "sort_order": 8, "dry_run": True})

    def test_invalid_format_rejected(self):
        with self.assertRaises(CommandError):
            self.run_cmd(name="Level 8", format="bogus")
        with self.assertRaises(CommandError):
            self.run_cmd(name="Level 8", dry_run=True, format="bogus")
        self.assertEqual(self.stored().name, "Level 6")

    def test_json_errors_still_command_error(self):
        for kwargs in ({"name": "  "}, {"sort_order": -5}, {}):
            with self.assertRaises(CommandError):
                self.run_cmd(format="json", **kwargs)
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, name="X", format="json")
        self.assertEqual(self.stored().name, "Level 6")
