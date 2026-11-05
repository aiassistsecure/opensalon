"""Tests for the export_punctuality management command.

The command is a thin wrapper around the
``team.punctuality_export`` services: these tests pin that
its CSV stdout and file output match
``export_punctuality_csv`` verbatim, that its JSON output
parses and equals the dict rows from ``export_punctuality``,
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
from team.models import AttendanceRecord, RosterPattern, StaffMember
from team.punctuality_export import (
    export_punctuality,
    export_punctuality_csv,
)

DAY1 = datetime.date(2026, 11, 2)  # Monday
DAY2 = datetime.date(2026, 11, 3)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


class ExportPunctualityCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        for weekday in (0, 1):
            RosterPattern.objects.create(
                staff_member=self.staff, weekday=weekday,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(17, 0))
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_in",
            recorded_at=at(DAY1, 9, 10))

    def run_export(self, **kwargs):
        out = io.StringIO()
        call_command("export_punctuality", stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service(self):
        out = self.run_export(
            salon_id=self.salon.pk, start_date=DAY1, end_date=DAY2)
        self.assertEqual(
            out, export_punctuality_csv(self.salon, DAY1, DAY2))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_punctuality", "--salon-id", str(self.salon.pk),
            "--start-date", DAY1.isoformat(),
            "--end-date", DAY2.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_punctuality_csv(self.salon, DAY1, DAY2))

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "punctuality.csv")
            out = self.run_export(
                salon_id=self.salon.pk, start_date=DAY1,
                end_date=DAY2, output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(),
                    export_punctuality_csv(self.salon, DAY1, DAY2))

    def test_default_format_is_csv_byte_identical(self):
        out = self.run_export(
            salon_id=self.salon.pk, start_date=DAY1, end_date=DAY2)
        self.assertEqual(
            out, export_punctuality_csv(self.salon, DAY1, DAY2))

    def test_explicit_csv_format_matches_service(self):
        out = self.run_export(
            salon_id=self.salon.pk, start_date=DAY1, end_date=DAY2,
            format="csv")
        self.assertEqual(
            out, export_punctuality_csv(self.salon, DAY1, DAY2))

    def test_csv_flag_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_punctuality", "--salon-id", str(self.salon.pk),
            "--start-date", DAY1.isoformat(),
            "--end-date", DAY2.isoformat(), "--format", "csv",
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_punctuality_csv(self.salon, DAY1, DAY2))

    def test_json_output_parses_and_equals_dict_service_rows(self):
        out = self.run_export(
            salon_id=self.salon.pk, start_date=DAY1, end_date=DAY2,
            format="json")
        self.assertEqual(
            json.loads(out),
            export_punctuality(self.salon, DAY1, DAY2))
        self.assertIn("Stylist One", out)

    def test_json_flag_matches_dict_service(self):
        out = io.StringIO()
        call_command(
            "export_punctuality", "--salon-id", str(self.salon.pk),
            "--start-date", DAY1.isoformat(),
            "--end-date", DAY2.isoformat(), "--format", "json",
            stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_punctuality(self.salon, DAY1, DAY2))

    def test_json_composes_with_date_range(self):
        out = self.run_export(
            salon_id=self.salon.pk, start_date=DAY1, end_date=DAY1,
            format="json")
        self.assertEqual(
            json.loads(out),
            export_punctuality(self.salon, DAY1, DAY1))
        self.assertIn(DAY1.isoformat(), out)

    def test_json_output_file_matches_dict_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "punctuality.json")
            out = self.run_export(
                salon_id=self.salon.pk, start_date=DAY1,
                end_date=DAY2, format="json", output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    json.loads(fh.read()),
                    export_punctuality(self.salon, DAY1, DAY2))

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk, start_date=DAY1,
                end_date=DAY2, format="xml")

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_punctuality", "--salon-id", str(self.salon.pk),
                "--start-date", DAY1.isoformat(),
                "--end-date", DAY2.isoformat(), "--format", "xml",
                stdout=io.StringIO())

    def test_json_reversed_range_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk, start_date=DAY2,
                end_date=DAY1, format="json")

    def test_unknown_salon_id_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk + 1000,
                start_date=DAY1, end_date=DAY2)

    def test_invalid_date_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk,
                start_date="not-a-date", end_date=DAY2)
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk,
                start_date=DAY1, end_date="2026-13-40")

    def test_reversed_range_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk,
                start_date=DAY2, end_date=DAY1)

    def test_unwritable_output_is_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing", "punctuality.csv")
            with self.assertRaises(CommandError):
                self.run_export(
                    salon_id=self.salon.pk, start_date=DAY1,
                    end_date=DAY2, output=path)
