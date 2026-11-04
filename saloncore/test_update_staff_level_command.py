import io

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from saloncore.add_staff_level import add_staff_level
from saloncore.models import Salon, StaffLevel


class UpdateStaffLevelCommandTests(TestCase):
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

    def test_happy_path_partial(self):
        text = self.run_cmd(name="Level 8", sort_order=8)
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Level 8", 8, True))
        self.assertIn(f"Updated staff level {self.level.pk}", text)
        self.assertIn("Level 8", text)

    def test_flag_form_inactive(self):
        out = io.StringIO()
        call_command(
            "update_staff_level", "--salon-id", str(self.salon.pk),
            "--staff-level-id", str(self.level.pk),
            "--inactive", stdout=out)
        self.assertFalse(self.stored().active)
        self.assertIn("active=False", out.getvalue())

    def test_flag_form_active_reactivates(self):
        self.level.active = False
        self.level.save()
        out = io.StringIO()
        call_command(
            "update_staff_level", "--salon-id", str(self.salon.pk),
            "--staff-level-id", str(self.level.pk), "--active", stdout=out)
        self.assertTrue(self.stored().active)

    def test_both_active_and_inactive_refused(self):
        out = io.StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "update_staff_level", "--salon-id", str(self.salon.pk),
                "--staff-level-id", str(self.level.pk),
                "--active", "--inactive", stdout=out)
        self.assertTrue(self.stored().active)

    def test_dry_run_writes_nothing_and_previews(self):
        text = self.run_cmd(name="Level 8", sort_order=8, dry_run=True)
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Level 6", 6, True))
        self.assertIn("Dry run: would update staff level", text)
        self.assertIn("name='Level 8'", text)
        self.assertIn("sort_order=8", text)
        self.assertIn("no staff level written", text)

    def test_dry_run_invalid_and_no_field_write_nothing(self):
        for kwargs in ({"name": "  "}, {"sort_order": -1}, {}):
            with self.assertRaises(CommandError):
                self.run_cmd(dry_run=True, **kwargs)
        self.assertEqual(self.stored().name, "Level 6")

    def test_no_field_given_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmd()
        self.assertEqual(self.stored().name, "Level 6")

    def test_cross_salon_level_refused(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = add_staff_level(other, "Level 1")
        with self.assertRaises(CommandError):
            self.run_cmd(staff_level_id=foreign.pk, name="X")
        self.assertEqual(self.stored().name, "Level 6")

    def test_unknown_salon_or_level_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, name="X")
        with self.assertRaises(CommandError):
            self.run_cmd(staff_level_id=999999, name="X")

    def test_blank_name_and_bad_sort_order_raise(self):
        for kwargs in ({"name": "  "}, {"sort_order": -5}):
            with self.assertRaises(CommandError):
                self.run_cmd(**kwargs)
        self.assertEqual(self.stored().name, "Level 6")
