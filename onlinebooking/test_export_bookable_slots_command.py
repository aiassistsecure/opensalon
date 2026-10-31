"""Tests for the export_bookable_slots management command.

The command is a thin wrapper around
``onlinebooking.bookable_slots_export.export_bookable_slots_csv``:
these tests pin that its stdout and file output match that
service verbatim, that salon/service scoping forwards to the
service, and that an unknown salon, an unknown service, an
invalid date, and unwritable output fail cleanly as
``CommandError``. Fixtures are tiny synthetic records -- unit
logic only.

The command class is loaded explicitly via
``load_command_class("onlinebooking", "export_bookable_slots")``
and passed to ``call_command`` so these tests pin this app's
command regardless of any global command-name collision.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase

from onlinebooking.bookable_slots_export import export_bookable_slots_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday


def _cmd():
    return load_command_class("onlinebooking", "export_bookable_slots")


class ExportBookableSlotsCommandTests(TestCase):
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
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))

    def run_export(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("service_id", self.service.pk)
        kwargs.setdefault("date", MONDAY)
        call_command(_cmd(), stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service(self):
        out = self.run_export()
        self.assertEqual(
            out, export_bookable_slots_csv(
                self.salon, self.service, MONDAY))
        self.assertIn("Online Stylist", out)

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(
            _cmd(), "--salon-id", str(self.salon.pk),
            "--service-id", str(self.service.pk),
            "--date", MONDAY.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(), export_bookable_slots_csv(
                self.salon, self.service, MONDAY))

    def test_stdout_matches_service_for_empty_day(self):
        tuesday = MONDAY + datetime.timedelta(days=1)
        out = self.run_export(date=tuesday)
        self.assertEqual(
            out, export_bookable_slots_csv(
                self.salon, self.service, tuesday))

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bookable_slots.csv")
            out = self.run_export(output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(), export_bookable_slots_csv(
                        self.salon, self.service, MONDAY))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(salon_id=self.salon.pk + 999)

    def test_unknown_service_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(service_id=self.service.pk + 999)

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(date="not-a-date")

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "bookable_slots.csv")
            with self.assertRaises(CommandError):
                self.run_export(output=path)
