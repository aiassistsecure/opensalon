import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from insights.prior_period_export import export_prior_period_csv
from saloncore.models import Salon

START = datetime.date(2026, 11, 2)
END = datetime.date(2026, 11, 8)


class ExportPriorPeriodCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Example Salon", timezone="UTC")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_period", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_period_csv(self.salon, START, END))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command("export_prior_period", "--salon-id", str(self.salon.pk),
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_period_csv(self.salon, START, END))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior.csv")
            call_command("export_prior_period", salon_id=self.salon.pk,
                         start_date=START, end_date=END, output=path,
                         stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(written,
                         export_prior_period_csv(self.salon, START, END))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_period",
                         salon_id=self.salon.pk + 999,
                         start_date=START, end_date=END,
                         stdout=io.StringIO())

    def test_missing_and_invalid_dates_raise_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_period", salon_id=self.salon.pk,
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_period", salon_id=self.salon.pk,
                         start_date="not-a-date", end_date=END,
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_period", "--salon-id",
                         str(self.salon.pk), "--start-date", "2026-13-40",
                         "--end-date", END.isoformat(), stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_period", salon_id=self.salon.pk,
                         start_date=END, end_date=START,
                         stdout=io.StringIO())
