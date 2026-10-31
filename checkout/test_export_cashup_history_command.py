import datetime
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.cashup_history_export import export_cashup_history_csv
from checkout.models import Cashup
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _stamp(day, hour=9):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)))


class ExportCashupHistoryCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        Cashup.objects.create(
            salon=self.salon, period_start=_stamp(DAY, 9),
            period_end=_stamp(DAY, 10),
            tender_totals={"cash": "85.00"},
            total=Decimal("85.00"), note="midday")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_cashup_history", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_cashup_history_csv(self.salon, DAY, DAY))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_cashup_history", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_cashup_history_csv(self.salon, DAY, DAY))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cashup_history.csv")
            call_command(
                "export_cashup_history", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_cashup_history_csv(self.salon, DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_cashup_history", salon_id=self.salon.pk + 999,
                start_date=DAY, end_date=DAY, stdout=io.StringIO())

    def test_service_errors_propagate(self):
        with self.assertRaises(ValueError):
            call_command(
                "export_cashup_history", salon_id=self.salon.pk,
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())
