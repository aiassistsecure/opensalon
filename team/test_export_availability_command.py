"""Tests for the export_availability management command.

The command is a thin wrapper around the
``team.availability_export`` services: these tests pin that
its CSV stdout and file output match
``export_availability_csv`` verbatim, that its JSON output
parses and equals the dict rows from ``export_availability``
(the module-tail alias of ``export_salon_roster``) -- i.e.
exactly the rows the CSV export serialises -- and that
invalid input raises CommandError.
Fixtures are tiny synthetic records -- unit logic only.
"""
import csv
import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from saloncore.models import Salon
from team.availability_export import (
    export_availability,
    export_availability_csv,
)
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

    def test_default_format_is_csv_byte_identical(self):
        out = self.run_export(
            salon_id=self.salon.pk, date=MONDAY)
        self.assertEqual(
            out, export_availability_csv(self.salon, MONDAY))

    def test_explicit_csv_format_matches_service(self):
        out = self.run_export(
            salon_id=self.salon.pk, date=MONDAY, format="csv")
        self.assertEqual(
            out, export_availability_csv(self.salon, MONDAY))

    def test_csv_flag_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_availability", "--salon-id", str(self.salon.pk),
            "--date", MONDAY.isoformat(), "--format", "csv",
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_availability_csv(self.salon, MONDAY))

    def test_json_output_parses_and_equals_dict_service_rows(self):
        out = self.run_export(
            salon_id=self.salon.pk, date=MONDAY, format="json")
        rows = export_availability(self.salon, MONDAY)
        self.assertEqual(json.loads(out), rows)
        self.assertEqual(
            out, json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_rows_are_exactly_csv_rows(self):
        json_out = self.run_export(
            salon_id=self.salon.pk, date=MONDAY, format="json")
        csv_out = self.run_export(
            salon_id=self.salon.pk, date=MONDAY, format="csv")
        self.assertEqual(
            csv_out, export_availability_csv(self.salon, MONDAY))
        csv_rows = list(csv.DictReader(io.StringIO(csv_out)))
        json_rows = json.loads(json_out)
        self.assertEqual(len(json_rows), len(csv_rows))
        for json_row, csv_row in zip(json_rows, csv_rows):
            self.assertEqual(list(json_row.keys()), list(csv_row.keys()))
            self.assertEqual(csv_row, {
                key: ("" if value is None else str(value))
                for key, value in json_row.items()})

    def test_json_flag_matches_dict_service(self):
        out = io.StringIO()
        call_command(
            "export_availability", "--salon-id", str(self.salon.pk),
            "--date", MONDAY.isoformat(), "--format", "json",
            stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_availability(self.salon, MONDAY))

    def test_json_composes_with_date(self):
        tuesday = MONDAY + datetime.timedelta(days=1)
        out = self.run_export(
            salon_id=self.salon.pk, date=tuesday, format="json")
        self.assertEqual(
            json.loads(out), export_availability(self.salon, tuesday))

    def test_json_output_file_matches_dict_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "availability.json")
            out = self.run_export(
                salon_id=self.salon.pk, date=MONDAY,
                format="json", output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
            rows = export_availability(self.salon, MONDAY)
            self.assertEqual(json.loads(written), rows)
            self.assertEqual(
                written,
                json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(
                salon_id=self.salon.pk, date=MONDAY, format="xml")

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_availability", "--salon-id", str(self.salon.pk),
                "--date", MONDAY.isoformat(), "--format", "xml",
                stdout=io.StringIO())

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
