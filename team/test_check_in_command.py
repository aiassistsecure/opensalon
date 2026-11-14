"""Tests for the check_in management command.

The command is a thin wrapper around
``team.availability.check_in``: these tests pin that it
records attendance through the service and that invalid
input raises CommandError. Fixtures are tiny synthetic
records -- unit logic only.
"""
import datetime
import io
import json

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.models import AttendanceRecord, StaffMember

AT = datetime.datetime(2026, 11, 2, 9, 0, tzinfo=datetime.timezone.utc)


class CheckInCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        call_command("check_in", stdout=out, **kwargs)
        return out.getvalue()

    def test_happy_path_records_attendance_via_service(self):
        out = self.run_cmd(
            staff_member_id=self.staff.pk, at=AT.isoformat(),
            note="On time")
        record = AttendanceRecord.objects.get(staff_member=self.staff)
        self.assertEqual(
            record.event_type, AttendanceRecord.EventType.CHECK_IN)
        self.assertEqual(record.recorded_at, AT)
        self.assertEqual(record.note, "On time")
        self.assertTrue(self.staff.is_checked_in())
        self.assertIn("Stylist One", out)

    def test_happy_path_via_cli_args_defaults_note(self):
        out = io.StringIO()
        call_command(
            "check_in", "--staff-member-id", str(self.staff.pk),
            "--at", AT.isoformat(), stdout=out)
        record = AttendanceRecord.objects.get(staff_member=self.staff)
        self.assertEqual(record.recorded_at, AT)
        self.assertEqual(record.note, "")
        self.assertIn("Stylist One", out.getvalue())

    def test_default_text_output_unchanged(self):
        out = self.run_cmd(
            staff_member_id=self.staff.pk, at=AT.isoformat())
        self.assertEqual(out, f"Checked in Stylist One at {AT}.\n")

    def test_default_text_dry_run_output_unchanged(self):
        out = self.run_cmd(
            staff_member_id=self.staff.pk, at=AT.isoformat(),
            dry_run=True)
        self.assertEqual(
            out,
            "Dry run: would create AttendanceRecord "
            "staff_member=Stylist One "
            f"staff_member_id={self.staff.pk} "
            "event_type=check_in "
            f"recorded_at={AT} "
            "note='' -- no record written.\n")
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_format_json_output(self):
        out = self.run_cmd(
            staff_member_id=self.staff.pk, at=AT.isoformat(),
            note="On time", format="json")
        self.assertEqual(out.count("\n"), 1)
        self.assertNotIn("Checked in", out)
        payload = json.loads(out)
        record = AttendanceRecord.objects.get(staff_member=self.staff)
        self.assertEqual(payload["attendance_record_id"], record.pk)
        self.assertEqual(payload["staff_member_id"], self.staff.pk)
        self.assertEqual(payload["salon_id"], self.salon.pk)
        self.assertEqual(payload["recorded_at"], AT.isoformat())
        self.assertEqual(payload["event_type"], "check_in")
        self.assertEqual(payload["note"], "On time")
        self.assertIs(payload["dry_run"], False)

    def test_format_json_dry_run_writes_nothing(self):
        out = self.run_cmd(
            staff_member_id=self.staff.pk, at=AT.isoformat(),
            dry_run=True, format="json")
        payload = json.loads(out)
        self.assertIsNone(payload["attendance_record_id"])
        self.assertEqual(payload["staff_member_id"], self.staff.pk)
        self.assertEqual(payload["salon_id"], self.salon.pk)
        self.assertEqual(payload["recorded_at"], AT.isoformat())
        self.assertIs(payload["dry_run"], True)
        self.assertEqual(AttendanceRecord.objects.count(), 0)
        self.assertFalse(self.staff.is_checked_in())

    def test_format_json_unknown_staff_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_cmd(
                staff_member_id=self.staff.pk + 1000, format="json")
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_unknown_staff_id_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_cmd(staff_member_id=self.staff.pk + 1000)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_bad_datetime_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_cmd(
                staff_member_id=self.staff.pk, at="not-a-datetime")
        self.assertEqual(AttendanceRecord.objects.count(), 0)
