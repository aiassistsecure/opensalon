import io
import json

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from saloncore.models import Salon, StaffLevel


class AddStaffLevelCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        call_command("add_staff_level", stdout=out, **kwargs)
        return out.getvalue()

    def test_happy_path(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Level 6", sort_order=6)
        (lvl,) = StaffLevel.objects.all()
        self.assertEqual(
            (lvl.salon, lvl.name, lvl.sort_order, lvl.active),
            (self.salon, "Level 6", 6, True))
        self.assertIn(f"Created staff level {lvl.pk}", text)
        self.assertIn("Level 6", text)

    def test_flag_form_with_inactive(self):
        out = io.StringIO()
        call_command(
            "add_staff_level", "--salon-id", str(self.salon.pk),
            "--name", "Junior", "--sort-order", "1",
            "--inactive", stdout=out)
        (lvl,) = StaffLevel.objects.all()
        self.assertEqual((lvl.sort_order, lvl.active), (1, False))
        self.assertIn("active=False", out.getvalue())

    def test_dry_run_writes_nothing_and_previews(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Level 6",
            sort_order=6, dry_run=True)
        self.assertEqual(StaffLevel.objects.count(), 0)
        self.assertIn("Dry run: would create staff level", text)
        self.assertIn("Level 6", text)
        self.assertIn("sort_order=6", text)
        self.assertIn("no staff level written", text)

    def test_dry_run_invalid_writes_nothing(self):
        for kwargs in ({"name": "  "}, {"name": "L", "sort_order": -1}):
            with self.assertRaises(CommandError):
                self.run_cmd(salon_id=self.salon.pk, dry_run=True, **kwargs)
        self.assertEqual(StaffLevel.objects.count(), 0)

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, name="Level 1")
        self.assertEqual(StaffLevel.objects.count(), 0)

    def test_blank_name_and_bad_sort_order_raise(self):
        for kwargs in ({"name": "  "}, {"name": "L", "sort_order": -5}):
            with self.assertRaises(CommandError):
                self.run_cmd(salon_id=self.salon.pk, **kwargs)
        self.assertEqual(StaffLevel.objects.count(), 0)

    def test_explicit_text_format_matches_default(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Level 6",
            sort_order=6, format="text")
        (lvl,) = StaffLevel.objects.all()
        self.assertEqual(
            text,
            f"Created staff level {lvl.pk}: 'Level 6' "
            f"in salon {self.salon.pk}: sort_order=6 "
            "active=True.\n")

    def test_json_output_parses_and_carries_facts(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Level 6",
            sort_order=6, format="json")
        (lvl,) = StaffLevel.objects.all()
        self.assertEqual(
            (lvl.salon, lvl.name, lvl.sort_order, lvl.active),
            (self.salon, "Level 6", 6, True))
        self.assertNotIn("Created staff level", text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertEqual(json.loads(text), {
            "id": lvl.pk, "name": "Level 6",
            "salon_id": self.salon.pk,
            "sort_order": 6, "active": True,
            "dry_run": False})

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(
            "add_staff_level", "--salon-id", str(self.salon.pk),
            "--name", "Junior", "--sort-order", "1",
            "--inactive", "--format", "json", stdout=out)
        row = json.loads(out.getvalue())
        (lvl,) = StaffLevel.objects.all()
        self.assertEqual(
            (row["id"], row["salon_id"], row["sort_order"],
             row["active"], row["dry_run"]),
            (lvl.pk, self.salon.pk, 1, False, False))

    def test_dry_run_json_reports_dry_run_and_writes_nothing(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Level 6",
            sort_order=6, dry_run=True, format="json")
        self.assertEqual(StaffLevel.objects.count(), 0)
        self.assertNotIn("Dry run", text)
        self.assertEqual(json.loads(text), {
            "id": None, "name": "Level 6",
            "salon_id": self.salon.pk,
            "sort_order": 6, "active": True,
            "dry_run": True})

    def test_json_errors_still_command_error(self):
        for kwargs in ({"name": "  "}, {"name": "L", "sort_order": -1}):
            with self.assertRaises(CommandError):
                self.run_cmd(
                    salon_id=self.salon.pk, format="json", **kwargs)
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, name="Level 1", format="json")
        with self.assertRaises(CommandError):
            self.run_cmd(
                salon_id=self.salon.pk, name="Level 1",
                dry_run=True, format="bogus")
        self.assertEqual(StaffLevel.objects.count(), 0)
