"""Tests for the export_receipt management command.

The command is a thin wrapper around
``checkout.receipt_export.export_receipts``: these tests pin
that its stdout and file output match that service verbatim
(serialized as JSON, as the service builds JSON-serializable
rows, or as CSV rendering those same rows under
``EXPORT_FIELDNAMES``) and that unknown salons, bad dates,
reversed ranges, invalid formats, and unwritable output fail
cleanly as ``CommandError``.
Fixtures are tiny synthetic records -- unit logic only.
"""
import csv
import datetime
import io
import json
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Receipt, Sale, SaleItem
from checkout.receipt_export import EXPORT_FIELDNAMES, export_receipts
from checkout.receipts import build_receipt
from clients.models import Client
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _aware(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour)))


def _service_text(salon, date_from=None, date_to=None):
    return json.dumps(
        export_receipts(date_from, date_to, salon=salon), indent=2) + "\n"


def _csv_text(salon, date_from=None, date_to=None):
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for row in export_receipts(date_from, date_to, salon=salon):
        writer.writerow(row)
    return buffer.getvalue()


def _as_csv_values(rows):
    return [
        {key: ("" if value is None else str(value))
         for key, value in row.items()}
        for row in rows
    ]


class ExportReceiptCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example",
            email="client@example.com")

    def _receipt(self, issued_day, salon=None, client="default"):
        sale = Sale.objects.create(
            salon=salon or self.salon,
            client=self.client if client == "default" else client,
            status=Sale.Status.COMPLETED,
            completed_at=_aware(issued_day))
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal("85.00"))
        receipt = build_receipt(sale)
        Receipt.objects.filter(pk=receipt.pk).update(
            issued_at=_aware(issued_day))
        receipt.refresh_from_db()
        return receipt

    def test_stdout_matches_service(self):
        self._receipt(DAY)
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), _service_text(self.salon, DAY, DAY))

    def test_stdout_matches_service_with_string_date_args(self):
        self._receipt(DAY)
        out = io.StringIO()
        call_command(
            "export_receipt", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", NEXT.isoformat(),
            stdout=out)
        self.assertEqual(out.getvalue(), _service_text(self.salon, DAY, NEXT))

    def test_stdout_matches_service_when_dates_omitted(self):
        self._receipt(DAY)
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), _service_text(self.salon))

    def test_salon_scoping_excludes_other_salons(self):
        own = self._receipt(DAY)
        other_salon = Salon.objects.create(name="Other Salon")
        self._receipt(DAY, salon=other_salon, client=None)
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), _service_text(self.salon, DAY, DAY))
        rows = json.loads(out.getvalue())
        self.assertEqual([r["id"] for r in rows], [own.pk])

    def test_output_file_matches_service(self):
        self._receipt(DAY)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "receipts.json")
            call_command(
                "export_receipt", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(written, _service_text(self.salon, DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_receipt", salon_id=self.salon.pk + 999,
                start_date=DAY, end_date=DAY, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        self._receipt(DAY)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "no-such-dir", "receipts.json")
            with self.assertRaises(CommandError):
                call_command(
                    "export_receipt", salon_id=self.salon.pk,
                    start_date=DAY, end_date=DAY, output=path,
                    stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_receipt", salon_id=self.salon.pk,
                start_date="not-a-date", end_date=DAY,
                stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_receipt", salon_id=self.salon.pk,
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())

    def test_default_format_remains_json(self):
        self._receipt(DAY)
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), _service_text(self.salon, DAY, DAY))

    def test_explicit_json_format_matches_service(self):
        self._receipt(DAY)
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, format="json", stdout=out)
        self.assertEqual(out.getvalue(), _service_text(self.salon, DAY, DAY))

    def test_csv_format_matches_expected_csv(self):
        self._receipt(DAY)
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, format="csv", stdout=out)
        self.assertEqual(out.getvalue(), _csv_text(self.salon, DAY, DAY))

    def test_csv_content_equals_json_rows(self):
        self._receipt(DAY)
        self._receipt(DAY, client=None)
        rows = export_receipts(DAY, DAY, salon=self.salon)
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, format="csv", stdout=out)
        parsed = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual(parsed, _as_csv_values(rows))
        self.assertEqual(parsed, _as_csv_values(json.loads(
            _service_text(self.salon, DAY, DAY))))

    def test_csv_header_and_field_order(self):
        self._receipt(DAY)
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, format="csv", stdout=out)
        lines = list(csv.reader(io.StringIO(out.getvalue())))
        self.assertEqual(lines[0], EXPORT_FIELDNAMES)
        self.assertEqual(
            EXPORT_FIELDNAMES,
            ["id", "receipt_id", "sale_id", "salon_id", "client_id",
             "salon_name", "total", "issued_at", "delivery_channel",
             "delivery_status", "recipient_email", "sent_at"])
        self.assertNotIn("provider_reference", lines[0])
        self.assertNotIn("provider_reference", out.getvalue())

    def test_csv_flag_matches_expected_csv(self):
        self._receipt(DAY)
        out = io.StringIO()
        call_command(
            "export_receipt", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), _csv_text(self.salon, DAY, DAY))

    def test_csv_output_file_matches_expected_csv(self):
        self._receipt(DAY)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "receipts.csv")
            call_command(
                "export_receipt", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY, format="csv",
                output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(written, _csv_text(self.salon, DAY, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_csv_empty_range_is_header_only(self):
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(), ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_receipt", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY, format="xml",
                stdout=io.StringIO())
