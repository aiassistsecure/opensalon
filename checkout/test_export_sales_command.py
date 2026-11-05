"""Tests for the export_sales management command.

The command is a thin wrapper around
``checkout.sale_export.export_sales_csv``: these tests pin
that its stdout and file output match that service verbatim,
that it scopes to the requested salon, and that unknown
salons, bad dates, reversed ranges, and unwritable output
fail cleanly as ``CommandError``.
"""
import datetime
import io
import json
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale
from checkout.sale_export import export_sales, export_sales_csv
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _stamp(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)),
        datetime.timezone.utc)


class ExportSalesCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Sale Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")

    def _sale(self, salon=None, day=DAY):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED,
            discount_amount=Decimal("10.00"))
        Sale.objects.filter(pk=sale.pk).update(created_at=_stamp(day))
        return sale

    def test_stdout_matches_service_no_range(self):
        self._sale()
        out = io.StringIO()
        call_command("export_sales", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_sales_csv(self.salon))

    def test_stdout_matches_service_with_range(self):
        self._sale()
        self._sale(day=NEXT + datetime.timedelta(days=5))
        out = io.StringIO()
        call_command(
            "export_sales", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(), export_sales_csv(self.salon, DAY, NEXT))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_scopes_to_requested_salon(self):
        self._sale()
        self._sale(salon=self.other)
        out = io.StringIO()
        call_command("export_sales", salon_id=self.other.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_sales_csv(self.other))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_output_file_matches_service(self):
        self._sale()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sales.csv")
            call_command(
                "export_sales", salon_id=self.salon.pk,
                output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(written, export_sales_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sales", salon_id=self.salon.pk + 999,
                stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        self._sale()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "no-such-dir", "sales.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_sales", salon_id=self.salon.pk,
                    output=path, stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sales", salon_id=self.salon.pk,
                start_date="not-a-date", stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sales", salon_id=self.salon.pk,
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())

    def test_end_date_without_start_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sales", salon_id=self.salon.pk,
                end_date=DAY, stdout=io.StringIO())


class ExportSalesCommandFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Sale Salon", timezone="UTC")

    def _sale(self, status=Sale.Status.COMPLETED, day=DAY):
        sale = Sale.objects.create(
            salon=self.salon, status=status,
            discount_amount=Decimal("10.00"))
        Sale.objects.filter(pk=sale.pk).update(created_at=_stamp(day))
        return sale

    def test_default_is_csv_byte_identical(self):
        self._sale()
        default_out = io.StringIO()
        call_command(
            "export_sales", salon_id=self.salon.pk, stdout=default_out)
        csv_out = io.StringIO()
        call_command(
            "export_sales", salon_id=self.salon.pk, format="csv",
            stdout=csv_out)
        self.assertEqual(default_out.getvalue(), csv_out.getvalue())
        self.assertEqual(
            default_out.getvalue(), export_sales_csv(self.salon))

    def test_explicit_csv_via_cli_matches_service(self):
        self._sale()
        out = io.StringIO()
        call_command(
            "export_sales", "--salon-id", str(self.salon.pk),
            "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), export_sales_csv(self.salon))

    def test_json_parses_and_equals_dict_service_rows(self):
        self._sale()
        self._sale(day=NEXT)
        out = io.StringIO()
        call_command(
            "export_sales", salon_id=self.salon.pk, format="json",
            stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()), export_sales(self.salon))

    def test_json_via_cli_matches_dict_service(self):
        self._sale()
        out = io.StringIO()
        call_command(
            "export_sales", "--salon-id", str(self.salon.pk),
            "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()), export_sales(self.salon))

    def test_json_composes_with_status_and_window(self):
        self._sale(Sale.Status.COMPLETED, DAY)
        kept = self._sale(Sale.Status.COMPLETED, NEXT)
        self._sale(Sale.Status.VOIDED, NEXT)
        self._sale(Sale.Status.COMPLETED, NEXT + datetime.timedelta(days=5))
        out = io.StringIO()
        call_command(
            "export_sales", "--salon-id", str(self.salon.pk),
            "--start-date", NEXT.isoformat(),
            "--end-date", NEXT.isoformat(),
            "--status", "completed", "--format", "json", stdout=out)
        expected = export_sales(
            self.salon, NEXT, NEXT, status="completed")
        self.assertEqual(json.loads(out.getvalue()), expected)
        self.assertEqual([row["id"] for row in expected], [kept.pk])

    def test_json_output_file_parses_and_equals_dict_service(self):
        self._sale()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sales.json")
            call_command(
                "export_sales", salon_id=self.salon.pk, format="json",
                output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(json.loads(written), export_sales(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sales", salon_id=self.salon.pk, format="xml",
                stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_sales", "--salon-id", str(self.salon.pk),
                "--format", "xml", stdout=io.StringIO())
