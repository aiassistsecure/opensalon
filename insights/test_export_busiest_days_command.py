import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from insights.busiest_export import (
    export_busiest_days,
    export_busiest_days_csv,
)
from saloncore.models import Salon

DAY = datetime.date(2026, 11, 2)
NEXT = DAY + datetime.timedelta(days=6)


class ExportBusiestDaysCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_busiest_days", salon_id=self.salon.pk,
            start_date=DAY, end_date=NEXT, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_busiest_days_csv(self.salon, DAY, NEXT))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_busiest_days", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_busiest_days_csv(self.salon, DAY, NEXT))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "busiest_days.csv")
            call_command(
                "export_busiest_days", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_busiest_days_csv(self.salon, DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_busiest_days", salon_id=self.salon.pk + 999,
                start_date=DAY, end_date=NEXT, stdout=io.StringIO())

    def test_reversed_range_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_busiest_days", salon_id=self.salon.pk,
            start_date=NEXT, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_busiest_days_csv(self.salon, NEXT, DAY))

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command(
            "export_busiest_days", salon_id=self.salon.pk,
            start_date=DAY, end_date=NEXT, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_busiest_days_csv(self.salon, DAY, NEXT))

    def test_explicit_csv_format_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_busiest_days", salon_id=self.salon.pk,
            start_date=DAY, end_date=NEXT, format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_busiest_days_csv(self.salon, DAY, NEXT))

    def test_csv_flag_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_busiest_days", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_busiest_days_csv(self.salon, DAY, NEXT))

    def test_json_output_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command(
            "export_busiest_days", salon_id=self.salon.pk,
            start_date=DAY, end_date=NEXT, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(rows, export_busiest_days(self.salon, DAY, NEXT))
        self.assertEqual(
            out.getvalue(),
            json.dumps(export_busiest_days(self.salon, DAY, NEXT),
                       indent=2) + "\n")

    def test_json_flag_matches_dict_service(self):
        out = io.StringIO()
        call_command(
            "export_busiest_days", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_busiest_days(self.salon, DAY, NEXT))

    def test_json_empty_salon_equals_dict_service_rows(self):
        # An empty salon still yields the service's seven zeroed
        # weekday rows, never an empty list.
        out = io.StringIO()
        call_command(
            "export_busiest_days", salon_id=self.salon.pk,
            start_date=DAY, end_date=NEXT, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(rows, export_busiest_days(self.salon, DAY, NEXT))
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(row["count"] == 0 for row in rows))

    def test_json_composes_with_date_window(self):
        out = io.StringIO()
        call_command(
            "export_busiest_days", salon_id=self.salon.pk,
            start_date=NEXT, end_date=DAY, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_busiest_days(self.salon, NEXT, DAY))

    def test_json_output_file_matches_dict_service(self):
        fd, path = tempfile.mkstemp(suffix=".json", dir=".")
        os.close(fd)
        try:
            out = io.StringIO()
            call_command(
                "export_busiest_days", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, format="json",
                output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
            self.assertEqual(
                json.loads(written),
                export_busiest_days(self.salon, DAY, NEXT))
            self.assertEqual(out.getvalue(), "")
        finally:
            os.unlink(path)

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_busiest_days", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, format="xml",
                stdout=io.StringIO())

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_busiest_days", "--salon-id", str(self.salon.pk),
                "--start-date", DAY.isoformat(),
                "--end-date", NEXT.isoformat(), "--format", "xml",
                stdout=io.StringIO())
