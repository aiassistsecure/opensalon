import io
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from saloncore.models import Salon, StaffLevel
from team.models import StaffMember
from team.update_staff_member import (
    update_staff_member, validate_update_staff_member)


class UpdateStaffMemberTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6")
        self.level2 = StaffLevel.objects.create(
            salon=self.salon, name="Level 7")
        self.other_level = StaffLevel.objects.create(
            salon=self.other, name="Level 6")
        self.member = StaffMember.objects.create(
            salon=self.salon, display_name="Dana",
            staff_level=self.level, email="dana@example.com",
            pin="1234")

    def test_updates_only_given_fields(self):
        m = update_staff_member(
            self.salon, self.member, display_name="  Dana D.  ",
            online_bookable=False, active=False)
        self.assertEqual(
            (m.display_name, m.staff_level, m.email, m.pin,
             m.online_bookable, m.active),
            ("Dana D.", self.level, "dana@example.com", "1234",
             False, False))
        self.member.refresh_from_db()
        self.assertEqual(self.member.display_name, "Dana D.")

    def test_level_email_pin_update_and_clear(self):
        m = update_staff_member(
            self.salon, self.member, staff_level=self.level2,
            email="new@example.com", pin="5678")
        self.assertEqual(
            (m.staff_level, m.email, m.pin),
            (self.level2, "new@example.com", "5678"))
        m = update_staff_member(
            self.salon, self.member, email="", pin="")
        self.assertEqual((m.email, m.pin), ("", ""))

    def test_no_fields_given_refused(self):
        with self.assertRaises(ValueError):
            update_staff_member(self.salon, self.member)
        with self.assertRaises(ValueError):
            validate_update_staff_member(self.salon, self.member)

    def test_keeping_own_email_and_pin_is_allowed(self):
        m = update_staff_member(
            self.salon, self.member, email="DANA@example.com",
            pin="1234", display_name="Dana")
        self.assertEqual(m.email, "DANA@example.com")

    def test_other_members_email_and_pin_refused(self):
        StaffMember.objects.create(
            salon=self.salon, display_name="Other",
            email="other@example.com", pin="9999")
        for kwargs in ({"email": "OTHER@example.com"},
                       {"pin": "9999"}, {"email": "bad"},
                       {"pin": "12"}, {"display_name": "  "},
                       {"online_bookable": "yes"}, {"active": 1}):
            with self.assertRaises(ValueError):
                update_staff_member(self.salon, self.member, **kwargs)
        self.member.refresh_from_db()
        self.assertEqual(
            (self.member.email, self.member.pin),
            ("dana@example.com", "1234"))

    def test_cross_salon_member_and_level_refused(self):
        stranger = StaffMember.objects.create(
            salon=self.other, display_name="Stranger")
        with self.assertRaises(ValueError):
            update_staff_member(
                self.salon, stranger, display_name="X")
        with self.assertRaises(ValueError):
            update_staff_member(
                self.salon, self.member,
                staff_level=self.other_level)

    def test_validate_writes_nothing_returns_given_only(self):
        cleaned = validate_update_staff_member(
            self.salon, self.member, display_name=" New ",
            pin="5678")
        self.assertEqual(
            cleaned, {"display_name": "New", "pin": "5678"})
        self.member.refresh_from_db()
        self.assertEqual(
            (self.member.display_name, self.member.pin),
            ("Dana", "1234"))


class UpdateStaffMemberCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 7")
        self.member = StaffMember.objects.create(
            salon=self.salon, display_name="Dana", pin="1234")

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        call_command("update_staff_member", stdout=out, **kwargs)
        return out.getvalue()

    def test_happy_path_updates_and_never_prints_pin(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, staff_member_id=self.member.pk,
            display_name="Dana D.", staff_level_id=self.level.pk,
            email="dana@example.com", pin="5678", active=False)
        self.member.refresh_from_db()
        self.assertEqual(
            (self.member.display_name, self.member.staff_level,
             self.member.email, self.member.pin, self.member.active),
            ("Dana D.", self.level, "dana@example.com", "5678", False))
        self.assertIn(f"Updated staff member {self.member.pk}", text)
        self.assertIn("pin_set=True", text)
        self.assertNotIn("5678", text)
        self.assertNotIn("1234", text)

    def test_flag_forms_online_bookable_and_inactive(self):
        out = io.StringIO()
        call_command(
            "update_staff_member", "--salon-id", str(self.salon.pk),
            "--staff-member-id", str(self.member.pk),
            "--no-online-bookable", "--inactive", stdout=out)
        self.member.refresh_from_db()
        self.assertEqual(
            (self.member.online_bookable, self.member.active),
            (False, False))
        out = io.StringIO()
        call_command(
            "update_staff_member", "--salon-id", str(self.salon.pk),
            "--staff-member-id", str(self.member.pk),
            "--online-bookable", "--active", stdout=out)
        self.member.refresh_from_db()
        self.assertEqual(
            (self.member.online_bookable, self.member.active),
            (True, True))

    def test_no_fields_and_unknown_ids_raise(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=self.salon.pk,
                         staff_member_id=self.member.pk)
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999,
                         staff_member_id=self.member.pk,
                         display_name="X")
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=self.salon.pk,
                         staff_member_id=999999, display_name="X")
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=self.salon.pk,
                         staff_member_id=self.member.pk,
                         staff_level_id=999999)

    def test_dry_run_uses_validate_only_and_writes_nothing(self):
        with mock.patch(
                "team.management.commands.update_staff_member"
                ".update_staff_member") as writer:
            text = self.run_cmd(
                salon_id=self.salon.pk,
                staff_member_id=self.member.pk,
                display_name="New Name", pin="5678", dry_run=True)
        writer.assert_not_called()
        self.member.refresh_from_db()
        self.assertEqual(
            (self.member.display_name, self.member.pin),
            ("Dana", "1234"))
        self.assertIn("Dry run: would update", text)
        self.assertIn("New Name", text)
        self.assertNotIn("5678", text)
        self.assertIn("no staff member written", text)

    def test_dry_run_invalid_writes_nothing(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=self.salon.pk,
                         staff_member_id=self.member.pk,
                         email="bad", dry_run=True)
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, "")
