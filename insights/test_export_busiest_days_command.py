import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from insights.busiest_export import export_busiest_days_csv
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
