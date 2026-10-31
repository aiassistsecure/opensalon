"""Tests for the export_daily_sales management command.

The command is a thin wrapper around
``checkout.daily_export.export_daily_sales_csv``: these tests
pin that its stdout and file output match that service verbatim
and that unknown salons, bad dates, and reversed ranges fail
cleanly as ``CommandError``. Fixtures are tiny synthetic
records -- unit logic only.
"""
import datetime
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.daily_export import export_daily_sales_csv
from checkout.models import Sale, SaleItem
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


class ExportDailySalesCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        SaleItem.objects.create(
            sale=sale, kind="service", description="service",
            unit_price=Decimal("85.00"), quantity=1)
        stamp = timezone.make_aware(
            datetime.datetime.combine(DAY, datetime.time(12, 0)),
            datetime.timezone.utc)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_daily_sales", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_daily_sales_csv(self.salon, DAY, DAY))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_daily_sales", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_daily_sales_csv(self.salon, DAY, NEXT))

    def test_stdout_single_day_when_end_date_omitted(self):
        out = io.StringIO()
        call_command(
            "export_daily_sales", salon_id=self.salon.pk,
            start_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_daily_sales_csv(self.salon, DAY, None))
        self.assertEqual(
            out.getvalue(), export_daily_sales_csv(self.salon, DAY))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "daily_sales.csv")
            call_command(
                "export_daily_sales", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_daily_sales_csv(self.salon, DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_daily_sales", salon_id=self.salon.pk + 999,
                start_date=DAY, end_date=DAY, stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_daily_sales", salon_id=self.salon.pk,
                start_date="not-a-date", end_date=DAY,
                stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_daily_sales", "--salon-id", str(self.salon.pk),
                "--start-date", "2026-13-40",
                "--end-date", DAY.isoformat(), stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_daily_sales", salon_id=self.salon.pk,
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())
