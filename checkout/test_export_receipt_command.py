"""Tests for the export_receipt management command.

The command is a thin wrapper around
``checkout.receipt_export.export_receipts``: these tests pin
that its stdout and file output match that service verbatim
(serialized as JSON, as the service builds JSON-serializable
rows) and that unknown salons, bad dates, reversed ranges,
and unwritable output fail cleanly as ``CommandError``.
Fixtures are tiny synthetic records -- unit logic only.
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

from checkout.models import Receipt, Sale, SaleItem
from checkout.receipt_export import export_receipts
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
