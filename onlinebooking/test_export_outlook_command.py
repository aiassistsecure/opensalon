"""Tests for the export_outlook management command.

The command is a thin wrapper around
``onlinebooking.outlook_export.export_outlook_csv``: these tests
pin that its stdout and file output match that service verbatim,
that its arguments forward to the service, and that an unknown
salon and an invalid duration fail as documented. Fixtures are
tiny synthetic records -- unit logic only.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from onlinebooking.outlook_export import export_outlook_csv
from saloncore.models import Salon
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday


class ExportOutlookCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist",
            online_bookable=True)
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(11, 0))

    def run_export(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("duration_minutes", 60)
        kwargs.setdefault("days", 1)
        kwargs.setdefault("start_date", MONDAY)
        call_command("export_outlook", stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service(self):
        out = self.run_export()
        self.assertEqual(
            out, export_outlook_csv(
                self.salon, 60, days=1, start_date=MONDAY))
        self.assertIn("Online Stylist", out)

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(
            "export_outlook", "--salon-id", str(self.salon.pk),
            "--duration-minutes", "60", "--days", "1",
            "--start-date", MONDAY.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_outlook_csv(self.salon, 60, days=1, start_date=MONDAY))

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "outlook.csv")
            out = self.run_export(output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(), export_outlook_csv(
                        self.salon, 60, days=1, start_date=MONDAY))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(salon_id=self.salon.pk + 999)

    def test_invalid_duration_propagates_service_error(self):
        for bad in (0, -30):
            with self.assertRaises(ValueError):
                self.run_export(duration_minutes=bad)

    def test_duration_and_step_forward_to_service(self):
        out = self.run_export(duration_minutes=30, step_minutes=30)
        self.assertEqual(
            out, export_outlook_csv(
                self.salon, 30, days=1, start_date=MONDAY,
                step_minutes=30))
        self.assertNotEqual(
            out, export_outlook_csv(
                self.salon, 60, days=1, start_date=MONDAY))
