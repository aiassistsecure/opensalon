import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from insights.trend_export import export_trend_csv
from saloncore.models import Salon

END = datetime.date(2026, 11, 8)


class ExportTrendCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_trend", salon_id=self.salon.pk,
            days=3, end_date=END, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_trend_csv(self.salon, days=3, end_date=END))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_trend", "--salon-id", str(self.salon.pk),
            "--days", "3", "--end-date", END.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_trend_csv(self.salon, days=3, end_date=END))

    def test_stdout_defaults_match_service(self):
        out = io.StringIO()
        call_command(
            "export_trend", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_trend_csv(self.salon, days=14, end_date=None))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "trend.csv")
            call_command(
                "export_trend", salon_id=self.salon.pk,
                days=3, end_date=END, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_trend_csv(self.salon, days=3, end_date=END))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_trend", salon_id=self.salon.pk + 999,
                days=3, end_date=END, stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_trend", salon_id=self.salon.pk,
                days=3, end_date="not-a-date", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_trend", "--salon-id", str(self.salon.pk),
                "--end-date", "2026-13-40", stdout=io.StringIO())

    def test_invalid_days_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_trend", salon_id=self.salon.pk,
                days="not-a-number", end_date=END, stdout=io.StringIO())
