"""Tests for the check_in management command.

The command is a thin wrapper around
``team.availability.check_in``: these tests pin that it
records attendance through the service and that invalid
input raises CommandError. Fixtures are tiny synthetic
records -- unit logic only.
"""
import datetime
import io

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

    def test_unknown_staff_id_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_cmd(staff_member_id=self.staff.pk + 1000)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_bad_datetime_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_cmd(
                staff_member_id=self.staff.pk, at="not-a-datetime")
        self.assertEqual(AttendanceRecord.objects.count(), 0)
