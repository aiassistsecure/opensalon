import io
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from saloncore.models import Salon, StaffLevel
from team.models import StaffMember


class AddStaffMemberCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6")

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        call_command("add_staff_member", stdout=out, **kwargs)
        return out.getvalue()

    def test_happy_path_creates_member(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, display_name="Dana Davalos",
            staff_level_id=self.level.pk,
            email="dana@example.com", pin="1234")
        (m,) = StaffMember.objects.all()
        self.assertEqual(
            (m.display_name, m.staff_level, m.online_bookable,
             m.email, m.pin),
            ("Dana Davalos", self.level, True,
             "dana@example.com", "1234"))
        self.assertIn(f"Created staff member {m.pk}", text)
        self.assertIn("Dana Davalos", text)
        self.assertNotIn("1234", text)

    def test_flag_form_no_online_bookable(self):
        out = io.StringIO()
        call_command(
            "add_staff_member", "--salon-id", str(self.salon.pk),
            "--display-name", "Dana", "--no-online-bookable",
            stdout=out)
        (m,) = StaffMember.objects.all()
        self.assertFalse(m.online_bookable)
        self.assertIn("online_bookable=False", out.getvalue())

    def test_flag_form_online_bookable_and_defaults(self):
        out = io.StringIO()
        call_command(
            "add_staff_member", "--salon-id", str(self.salon.pk),
            "--display-name", "Dana", "--online-bookable",
            stdout=out)
        (m,) = StaffMember.objects.all()
        self.assertEqual(
            (m.online_bookable, m.staff_level, m.email, m.pin),
            (True, None, "", ""))

    def test_dry_run_writes_nothing_and_previews(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, display_name="Dana",
            staff_level_id=self.level.pk,
            email="dana@example.com", pin="1234", dry_run=True)
        self.assertEqual(StaffMember.objects.count(), 0)
        self.assertIn("Dry run: would create staff member", text)
        self.assertIn("Dana", text)
        self.assertIn("pin_set=True", text)
        self.assertNotIn("1234", text)
        self.assertIn("no staff member written", text)

    def test_dry_run_never_calls_writer(self):
        with mock.patch(
                "team.management.commands.add_staff_member"
                ".add_staff_member") as writer:
            self.run_cmd(salon_id=self.salon.pk, display_name="Dana",
                         dry_run=True)
        writer.assert_not_called()
        self.assertEqual(StaffMember.objects.count(), 0)

    def test_dry_run_invalid_writes_nothing(self):
        StaffMember.objects.create(
            salon=self.salon, display_name="Existing", pin="1234")
        before = StaffMember.objects.count()
        for kwargs in ({"display_name": "  "},
                       {"display_name": "X", "email": "bad"},
                       {"display_name": "X", "pin": "1234"},
                       {"display_name": "X",
                        "staff_level_id": 999999}):
            with self.assertRaises(CommandError):
                self.run_cmd(
                    salon_id=self.salon.pk, dry_run=True, **kwargs)
        self.assertEqual(StaffMember.objects.count(), before)

    def test_unknown_salon_and_level_raise(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, display_name="X")
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=self.salon.pk, display_name="X",
                         staff_level_id=999999)
        self.assertEqual(StaffMember.objects.count(), 0)

    def test_cross_salon_level_raises(self):
        other = Salon.objects.create(name="Other Salon")
        other_level = StaffLevel.objects.create(
            salon=other, name="Level 9")
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=self.salon.pk, display_name="X",
                         staff_level_id=other_level.pk)
        self.assertEqual(StaffMember.objects.count(), 0)

    def test_duplicate_pin_and_email_raise(self):
        self.run_cmd(salon_id=self.salon.pk, display_name="Dana",
                     email="dana@example.com", pin="1234")
        for kwargs in ({"display_name": "Copy", "pin": "1234"},
                       {"display_name": "Copy",
                        "email": "DANA@example.com"}):
            with self.assertRaises(CommandError):
                self.run_cmd(salon_id=self.salon.pk, **kwargs)
        self.assertEqual(StaffMember.objects.count(), 1)

    def test_blank_name_and_bad_pin_raise(self):
        for kwargs in ({"display_name": "  "},
                       {"display_name": "X", "pin": "12"},
                       {"display_name": "X", "pin": "abcd"}):
            with self.assertRaises(CommandError):
                self.run_cmd(salon_id=self.salon.pk, **kwargs)
        self.assertEqual(StaffMember.objects.count(), 0)
