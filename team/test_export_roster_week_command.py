"""Tests for the export_roster_week management command.

The command is a thin wrapper around the
``team.roster_week_export`` services: these tests pin that
its CSV stdout and file output match
``export_roster_week_csv`` verbatim, that its JSON output
parses and equals the dict rows from ``export_roster_week``,
and that invalid input raises CommandError.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.models import RosterPattern, StaffMember
from team.roster_week_export import (
    export_roster_week,
    export_roster_week_csv,
)

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

    def test_default_format_is_csv_byte_identical(self):
        out = self.run_export(
            salon_id=self.salon.pk, week_start=MONDAY)
        self.assertEqual(
            out, export_roster_week_csv(self.salon, MONDAY))

    def test_explicit_csv_format_matches_service(self):
        out = self.run_export(
            salon_id=self.salon.pk, week_start=MONDAY, format="csv")
        self.assertEqual(
            out, export_roster_week_csv(self.salon, MONDAY))

    def test_csv_flag_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_roster_week", "--salon-id", str(self.salon.pk),
            "--week-start", MONDAY.isoformat(), "--format", "csv",
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_roster_week_csv(self.salon, MONDAY))

    def test_json_output_parses_and_equals_dict_service_rows(self):
        out = self.run_export(
            salon_id=self.salon.pk, week_start=MONDAY, format="json")
        self.assertEqual(
            json.loads(out), export_roster_week(self.salon, MONDAY))
        self.assertIn("Stylist One", out)

    def test_json_flag_matches_dict_service(self):
        out = io.StringIO()
        call_command(
            "export_roster_week", "--salon-id", str(self.salon.pk),
            "--week-start", MONDAY.isoformat(), "--format", "json",
            stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_roster_week(self.salon, MONDAY))

    def test_json_empty_salon_is_empty_list(self):
        empty = Salon.objects.create(name="Empty JSON", timezone="UTC")
        out = self.run_export(
            salon_id=empty.pk, week_start=MONDAY, format="json")
        self.assertEqual(json.loads(out), [])
        self.assertEqual(
            json.loads(out), export_roster_week(empty, MONDAY))

    def test_json_composes_with_week_start(self):
        other_monday = MONDAY + datetime.timedelta(days=7)
        out = self.run_export(
            salon_id=self.salon.pk, week_start=other_monday,
            format="json")
        self.assertEqual(
            json.loads(out),
            export_roster_week(self.salon, other_monday))
        self.assertIn(other_monday.isoformat(), out)

    def test_json_output_file_matches_dict_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "roster_week.json")
            out = self.run_export(
                salon_id=self.salon.pk, week_start=MONDAY,
                format="json", output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    json.loads(fh.read()),
                    export_roster_week(self.salon, MONDAY))

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk, week_start=MONDAY,
                format="xml")

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_roster_week", "--salon-id", str(self.salon.pk),
                "--week-start", MONDAY.isoformat(), "--format", "xml",
                stdout=io.StringIO())

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
