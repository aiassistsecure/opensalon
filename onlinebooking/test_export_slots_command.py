"""Tests for the export_slots management command.

The command is a thin wrapper around
``onlinebooking.slots_export.export_slots_csv``: these tests
pin that its stdout and file output match that service
verbatim, that salon/staff/date/duration/step arguments
forward to the service, and that an unknown salon, an unknown
staff member, an unknown service, a missing duration source,
an invalid date, a non-positive duration or step, and
unwritable output fail cleanly as ``CommandError``. Fixtures
are tiny synthetic records -- unit logic only.

The command class is loaded explicitly via
``load_command_class("onlinebooking", "export_slots")`` and
passed to ``call_command`` so these tests pin this app's
command regardless of any global command-name collision or
confusion with the bookings app's slot commands.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase

from onlinebooking.slots_export import export_slots_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday


def _cmd():
    return load_command_class("onlinebooking", "export_slots")


class ExportSlotsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist",
            online_bookable=True)
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(11, 0))

    def run_export(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("staff_id", self.staff.pk)
        kwargs.setdefault("date", MONDAY)
        kwargs.setdefault("duration_minutes", 60)
        call_command(_cmd(), stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service(self):
        out = self.run_export()
        self.assertEqual(
            out, export_slots_csv(self.salon, self.staff, MONDAY, 60))
        self.assertIn("Online Stylist", out)

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(
            _cmd(), "--salon-id", str(self.salon.pk),
            "--staff-id", str(self.staff.pk),
            "--date", MONDAY.isoformat(),
            "--duration-minutes", "60", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_slots_csv(self.salon, self.staff, MONDAY, 60))

    def test_step_minutes_passes_through(self):
        out = self.run_export(step_minutes=30)
        self.assertEqual(
            out, export_slots_csv(
                self.salon, self.staff, MONDAY, 60, step_minutes=30))

    def test_service_id_passes_service_object_through(self):
        out = self.run_export(
            duration_minutes=None, service_id=self.service.pk)
        self.assertEqual(
            out, export_slots_csv(
                self.salon, self.staff, MONDAY, self.service))

    def test_stdout_matches_service_for_empty_day(self):
        tuesday = MONDAY + datetime.timedelta(days=1)
        out = self.run_export(date=tuesday)
        self.assertEqual(
            out, export_slots_csv(self.salon, self.staff, tuesday, 60))

    def test_other_salon_staff_exports_header_only(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        out = self.run_export(salon_id=other.pk)
        self.assertEqual(
            out, export_slots_csv(other, self.staff, MONDAY, 60))

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "slots.csv")
            out = self.run_export(output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(), export_slots_csv(
                        self.salon, self.staff, MONDAY, 60))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(salon_id=self.salon.pk + 999)

    def test_unknown_staff_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(staff_id=self.staff.pk + 999)

    def test_unknown_service_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                duration_minutes=None, service_id=self.service.pk + 999)

    def test_missing_duration_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(duration_minutes=None)

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(date="not-a-date")

    def test_non_positive_duration_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(duration_minutes=0)

    def test_non_positive_step_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(step_minutes=0)

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "slots.csv")
            with self.assertRaises(CommandError):
                self.run_export(output=path)
