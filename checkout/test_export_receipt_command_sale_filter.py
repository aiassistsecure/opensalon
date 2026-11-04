"""Per-sale filter tests for the export_receipt command."""
import datetime
import io
import json
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Receipt, Sale, SaleItem
from checkout.receipt_export import export_receipts
from checkout.receipts import build_receipt
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)


def _aware(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour)))


def _service_text(salon, sale=None):
    return json.dumps(
        export_receipts(DAY, DAY, salon=salon, sale=sale), indent=2) + "\n"


class ExportReceiptCommandSaleFilterTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")

    def _receipt(self, salon=None):
        salon = salon or self.salon
        sale = Sale.objects.create(
            salon=salon, status=Sale.Status.COMPLETED,
            completed_at=_aware(DAY))
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal("85.00"))
        receipt = build_receipt(sale)
        Receipt.objects.filter(pk=receipt.pk).update(issued_at=_aware(DAY))
        receipt.refresh_from_db()
        return receipt

    def test_sale_id_kwarg_filters_to_one_sale(self):
        first = self._receipt()
        self._receipt()
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, sale_id=first.sale_id,
            stdout=out)
        self.assertEqual(out.getvalue(), _service_text(self.salon, first.sale))
        rows = json.loads(out.getvalue())
        self.assertEqual([r["id"] for r in rows], [first.pk])

    def test_sale_id_via_cli_flag(self):
        first = self._receipt()
        out = io.StringIO()
        call_command(
            "export_receipt", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--sale-id", str(first.sale_id), stdout=out)
        self.assertEqual(out.getvalue(), _service_text(self.salon, first.sale))

    def test_no_sale_id_is_salon_wide_default(self):
        self._receipt()
        self._receipt()
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), _service_text(self.salon))
        self.assertEqual(out.getvalue(), _service_text(self.salon, sale=None))

    def test_unknown_sale_id_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_receipt", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY, sale_id=999999,
                stdout=io.StringIO())

    def test_sale_from_other_salon_raises_command_error(self):
        theirs = self._receipt(salon=self.other)
        with self.assertRaises(CommandError):
            call_command(
                "export_receipt", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY, sale_id=theirs.sale_id,
                stdout=io.StringIO())
