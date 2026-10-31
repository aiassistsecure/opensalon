"""Tests for the export_roster_week management command.

The command is a thin wrapper around
``team.roster_week_export.export_roster_week_csv``: these
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
from team.models import RosterPattern, StaffMember
from team.roster_week_export import export_roster_week_csv

MONDAY = datetime.date(2026, 11, 2)


class ExportRosterWeekCommandTests(TestCase):
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
        call_command("export_roster_week", stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service(self):
        out = self.run_export(
            salon_id=self.salon.pk, week_start=MONDAY)
        self.assertEqual(
            out, export_roster_week_csv(self.salon, MONDAY))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_roster_week", "--salon-id", str(self.salon.pk),
            "--week-start", MONDAY.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_roster_week_csv(self.salon, MONDAY))

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "roster_week.csv")
            out = self.run_export(
                salon_id=self.salon.pk, week_start=MONDAY,
                output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(),
                    export_roster_week_csv(self.salon, MONDAY))

    def test_unknown_salon_id_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk + 1000, week_start=MONDAY)

    def test_invalid_date_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk, week_start="not-a-date")
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk, week_start="2026-13-40")

    def test_unwritable_output_is_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing", "roster_week.csv")
            with self.assertRaises(CommandError):
                self.run_export(
                    salon_id=self.salon.pk, week_start=MONDAY,
                    output=path)
