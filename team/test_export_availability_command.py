"""Tests for the export_availability management command.

The command is a thin wrapper around
``team.availability_export.export_availability_csv``: these
tests pin that its stdout and file output match that service
verbatim and that invalid input raises CommandError.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.availability_export import export_availability_csv
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)


class ExportAvailabilityCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0))

    def run_export(self, **kwargs):
        out = io.StringIO()
        call_command("export_availability", stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service(self):
        out = self.run_export(
            salon_id=self.salon.pk, date=MONDAY)
        self.assertEqual(
            out, export_availability_csv(self.salon, MONDAY))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_availability", "--salon-id", str(self.salon.pk),
            "--date", MONDAY.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_availability_csv(self.salon, MONDAY))

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "availability.csv")
            out = self.run_export(
                salon_id=self.salon.pk, date=MONDAY,
                output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(),
                    export_availability_csv(self.salon, MONDAY))

    def test_unknown_salon_id_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk + 1000, date=MONDAY)

    def test_invalid_date_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk, date="not-a-date")
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk, date="2026-13-40")

    def test_unwritable_output_is_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing", "availability.csv")
            with self.assertRaises(CommandError):
                self.run_export(
                    salon_id=self.salon.pk, date=MONDAY,
                    output=path)
