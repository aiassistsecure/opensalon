"""Per-sale filter tests for the receipt export service."""
import csv
import datetime
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Receipt, Sale, SaleItem
from checkout.receipt_export import (
    EXPORT_FIELDNAMES,
    export_receipts,
    export_receipts_csv,
)
from checkout.receipts import build_receipt
from saloncore.models import Salon


def _aware(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour)))


class ReceiptExportSaleFilterTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)

    def _receipt(self, salon=None):
        salon = salon or self.salon
        sale = Sale.objects.create(
            salon=salon, status=Sale.Status.COMPLETED,
            completed_at=_aware(self.day))
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal("85.00"))
        receipt = build_receipt(sale)
        Receipt.objects.filter(pk=receipt.pk).update(
            issued_at=_aware(self.day))
        receipt.refresh_from_db()
        return receipt

    def _empty_sale(self):
        return Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED,
            completed_at=_aware(self.day))

    def test_sale_instance_filters_to_that_sale(self):
        first = self._receipt()
        self._receipt()
        rows = export_receipts(self.day, self.day, salon=self.salon,
                               sale=first.sale)
        self.assertEqual([r["id"] for r in rows], [first.pk])
        self.assertEqual(rows[0]["sale_id"], first.sale_id)

    def test_sale_id_filters_to_that_sale(self):
        first = self._receipt()
        second = self._receipt()
        rows = export_receipts(self.day, self.day, salon=self.salon,
                               sale=second.sale_id)
        self.assertEqual([r["id"] for r in rows], [second.pk])
        self.assertEqual(rows[0]["sale_id"], second.sale_id)
        self.assertNotEqual(first.pk, second.pk)

    def test_unfiltered_unchanged(self):
        self._receipt()
        self._receipt()
        default = export_receipts(self.day, self.day, salon=self.salon)
        self.assertEqual(len(default), 2)
        self.assertEqual(
            export_receipts(self.day, self.day, salon=self.salon,
                            sale=None), default)
        self.assertEqual(
            export_receipts_csv(self.day, self.day, salon=self.salon,
                                sale=None),
            export_receipts_csv(self.day, self.day, salon=self.salon))

    def test_csv_and_list_agree(self):
        first = self._receipt()
        self._receipt()
        rows = export_receipts(self.day, self.day, salon=self.salon,
                               sale=first.sale)
        parsed = list(csv.DictReader(io.StringIO(export_receipts_csv(
            self.day, self.day, salon=self.salon, sale=first.sale))))
        self.assertEqual(len(parsed), 1)
        for key in EXPORT_FIELDNAMES:
            expected = "" if rows[0][key] is None else str(rows[0][key])
            self.assertEqual(parsed[0][key], expected)

    def test_empty_sale_is_empty_list_and_header_only_csv(self):
        self._receipt()
        empty = self._empty_sale()
        self.assertEqual(
            export_receipts(self.day, self.day, salon=self.salon,
                            sale=empty), [])
        self.assertEqual(
            export_receipts_csv(self.day, self.day, salon=self.salon,
                                sale=empty.pk),
            ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_unknown_sale_id_raises_value_error(self):
        self._receipt()
        with self.assertRaises(ValueError):
            export_receipts(self.day, self.day, salon=self.salon,
                            sale=999999)
        with self.assertRaises(ValueError):
            export_receipts_csv(self.day, self.day, salon=self.salon,
                                sale=999999)

    def test_unsaved_sale_instance_raises_value_error(self):
        unsaved = Sale(salon=self.salon, status=Sale.Status.COMPLETED)
        with self.assertRaises(ValueError):
            export_receipts(self.day, self.day, salon=self.salon,
                            sale=unsaved)

    def test_other_salon_sale_raises_value_error(self):
        self._receipt()
        theirs = self._receipt(salon=self.other)
        with self.assertRaises(ValueError):
            export_receipts(self.day, self.day, salon=self.salon,
                            sale=theirs.sale)
        with self.assertRaises(ValueError):
            export_receipts(self.day, self.day, salon=self.salon,
                            sale=theirs.sale_id)
        with self.assertRaises(ValueError):
            export_receipts_csv(self.day, self.day, salon=self.salon,
                                sale=theirs.sale)
        # The same sale resolves fine in its own salon.
        self.assertEqual(
            [r["id"] for r in export_receipts(
                self.day, self.day, salon=self.other, sale=theirs.sale)],
            [theirs.pk])

    def test_sale_filter_date_window_still_applies(self):
        receipt = self._receipt()
        other_day = self.day + datetime.timedelta(days=5)
        self.assertEqual(
            export_receipts(other_day, other_day, salon=self.salon,
                            sale=receipt.sale), [])

    def test_sale_is_keyword_only(self):
        receipt = self._receipt()
        with self.assertRaises(TypeError):
            export_receipts(self.day, self.day, self.salon, receipt.sale)
