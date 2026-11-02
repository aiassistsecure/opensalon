import io
import os
import tempfile
from datetime import date

from django.core.management import CommandError, call_command
from django.test import TestCase

from insights.attach_export import export_attach_rate_csv
from saloncore.models import Salon

START = date(2026, 11, 2)
END = date(2026, 11, 8)  # 7-day window START..END inclusive


class ExportAttachRateCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_attach_rate", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_attach_rate_csv(self.salon, days=7, end_date=END))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command("export_attach_rate", "--salon-id", str(self.salon.pk),
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_attach_rate_csv(self.salon, days=7, end_date=END))

    def test_days_window_matches_service(self):
        out = io.StringIO()
        call_command("export_attach_rate", salon_id=self.salon.pk,
                     days=3, end_date=END, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_attach_rate_csv(self.salon, days=3, end_date=END))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "attach.csv")
            call_command("export_attach_rate", salon_id=self.salon.pk,
                         start_date=START, end_date=END, output=path,
                         stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written,
            export_attach_rate_csv(self.salon, days=7, end_date=END))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_attach_rate", salon_id=self.salon.pk + 999,
                         start_date=START, end_date=END,
                         stdout=io.StringIO())

    def test_missing_dates_raise_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_attach_rate", salon_id=self.salon.pk,
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_attach_rate", salon_id=self.salon.pk,
                         start_date=START, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_attach_rate", salon_id=self.salon.pk,
                         end_date=END, stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_attach_rate", salon_id=self.salon.pk,
                         start_date="not-a-date", end_date=END,
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_attach_rate", "--salon-id",
                         str(self.salon.pk), "--start-date", START.isoformat(),
                         "--end-date", "2026-13-40", stdout=io.StringIO())

    def test_reversed_window_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_attach_rate", salon_id=self.salon.pk,
                         start_date=END, end_date=START,
                         stdout=io.StringIO())

    def test_invalid_days_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_attach_rate", salon_id=self.salon.pk,
                         days="not-a-number", end_date=END,
                         stdout=io.StringIO())
