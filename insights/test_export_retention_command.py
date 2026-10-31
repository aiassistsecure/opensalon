import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from insights.retention_export import export_retention_csv
from saloncore.models import Salon

START = datetime.date(2026, 11, 2)
END = datetime.date(2026, 11, 8)


class ExportRetentionCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_retention", salon_id=self.salon.pk,
            start_date=START, end_date=END, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_retention_csv(self.salon, START, END))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_retention", "--salon-id", str(self.salon.pk),
            "--start-date", START.isoformat(), "--end-date", END.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_retention_csv(self.salon, START, END))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "retention.csv")
            call_command(
                "export_retention", salon_id=self.salon.pk,
                start_date=START, end_date=END, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_retention_csv(self.salon, START, END))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_retention", salon_id=self.salon.pk + 999,
                start_date=START, end_date=END, stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_retention", salon_id=self.salon.pk,
                start_date="not-a-date", end_date=END,
                stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_retention", "--salon-id", str(self.salon.pk),
                "--start-date", START.isoformat(),
                "--end-date", "2026-13-40", stdout=io.StringIO())

    def test_missing_dates_raise_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_retention", salon_id=self.salon.pk,
                stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "retention.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_retention", salon_id=self.salon.pk,
                    start_date=START, end_date=END, output=path,
                    stdout=io.StringIO())
