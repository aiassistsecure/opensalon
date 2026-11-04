import io

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
