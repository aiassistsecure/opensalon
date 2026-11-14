import io
import json
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

    def test_default_active_and_inactive_flag(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, display_name="Dana")
        (m,) = StaffMember.objects.all()
        self.assertTrue(m.active)
        self.assertIn("active=True", text)
        out = io.StringIO()
        call_command(
            "add_staff_member", "--salon-id", str(self.salon.pk),
            "--display-name", "Ina", "--inactive", stdout=out)
        m2 = StaffMember.objects.get(display_name="Ina")
        self.assertFalse(m2.active)
        self.assertIn("active=False", out.getvalue())

    def test_dry_run_with_inactive_writes_nothing(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, display_name="Dana",
            inactive=True, dry_run=True)
        self.assertEqual(StaffMember.objects.count(), 0)
        self.assertIn("Dry run: would create staff member", text)
        self.assertIn("active=False", text)
        self.assertIn("no staff member written", text)
        out = io.StringIO()
        call_command(
            "add_staff_member", "--salon-id", str(self.salon.pk),
            "--display-name", "Dana", "--inactive", "--dry-run",
            stdout=out)
        self.assertEqual(StaffMember.objects.count(), 0)
        self.assertIn("active=False", out.getvalue())

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

    def test_default_text_output_unchanged(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, display_name="Dana")
        (m,) = StaffMember.objects.all()
        self.assertEqual(
            text,
            f"Created staff member {m.pk}: staff member 'Dana' "
            f"in salon {self.salon.pk}: staff_level_id=None "
            f"online_bookable=True email='' pin_set=False "
            f"active=True.\n")

    def test_default_text_dry_run_output_unchanged(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, display_name="Dana",
            dry_run=True)
        self.assertEqual(StaffMember.objects.count(), 0)
        self.assertEqual(
            text,
            f"Dry run: would create staff member 'Dana' "
            f"in salon {self.salon.pk}: staff_level_id=None "
            f"online_bookable=True email='' pin_set=False "
            f"active=True -- no staff member written.\n")

    def test_format_json_creates_and_reports_fields(self):
        out = io.StringIO()
        call_command(
            "add_staff_member", "--salon-id", str(self.salon.pk),
            "--display-name", "Dana Davalos",
            "--staff-level-id", str(self.level.pk),
            "--email", "dana@example.com", "--pin", "1234",
            "--no-online-bookable", "--inactive",
            "--format", "json", stdout=out)
        text = out.getvalue()
        (m,) = StaffMember.objects.all()
        payload = json.loads(text)
        self.assertEqual(payload, {
            "staff_member_id": m.pk,
            "salon_id": self.salon.pk,
            "display_name": "Dana Davalos",
            "staff_level_id": self.level.pk,
            "online_bookable": False,
            "email": "dana@example.com",
            "pin_set": True,
            "active": False,
            "dry_run": False})
        self.assertEqual(text.strip().count("\n"), 0)
        self.assertNotIn("Created staff member", text)
        self.assertNotIn("1234", text)

    def test_format_json_via_call_command_kwargs(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, display_name="Dana",
            format="json")
        (m,) = StaffMember.objects.all()
        payload = json.loads(text)
        self.assertEqual(payload["display_name"], "Dana")
        self.assertEqual(payload["staff_member_id"], m.pk)
        self.assertFalse(payload["dry_run"])
        self.assertFalse(payload["pin_set"])

    def test_dry_run_format_json_reports_and_writes_nothing(self):
        with mock.patch(
                "team.management.commands.add_staff_member"
                ".add_staff_member") as writer:
            out = io.StringIO()
            call_command(
                "add_staff_member", "--salon-id",
                str(self.salon.pk), "--display-name", "Dana",
                "--staff-level-id", str(self.level.pk),
                "--email", "dana@example.com", "--pin", "1234",
                "--dry-run", "--format", "json", stdout=out)
        writer.assert_not_called()
        self.assertEqual(StaffMember.objects.count(), 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload, {
            "staff_member_id": None,
            "salon_id": self.salon.pk,
            "display_name": "Dana",
            "staff_level_id": self.level.pk,
            "online_bookable": True,
            "email": "dana@example.com",
            "pin_set": True,
            "active": True,
            "dry_run": True})
        self.assertNotIn("1234", out.getvalue())

    def test_format_json_errors_still_command_error(self):
        with self.assertRaises(CommandError):
            self.run_cmd(
                salon_id=999999, display_name="X", format="json")
        with self.assertRaises(CommandError):
            self.run_cmd(
                salon_id=self.salon.pk, display_name="X",
                pin="12", format="json")
        with self.assertRaises(CommandError):
            self.run_cmd(
                salon_id=self.salon.pk, display_name="X",
                format="bogus")
        self.assertEqual(StaffMember.objects.count(), 0)

    def test_blank_name_and_bad_pin_raise(self):
        for kwargs in ({"display_name": "  "},
                       {"display_name": "X", "pin": "12"},
                       {"display_name": "X", "pin": "abcd"}):
            with self.assertRaises(CommandError):
                self.run_cmd(salon_id=self.salon.pk, **kwargs)
        self.assertEqual(StaffMember.objects.count(), 0)
