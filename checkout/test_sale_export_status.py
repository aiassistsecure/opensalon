"""Sale export --status filter: exact, composable, default off."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale
from checkout.sale_export import (
    SALE_EXPORT_FIELDNAMES,
    export_sales,
    export_sales_csv,
)
from saloncore.models import Salon


class SaleExportStatusTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Sale Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)
        self.next = self.day + datetime.timedelta(days=1)

    def _at(self, day, hour=12):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, 0)),
            datetime.timezone.utc)

    def _sale(self, status, day=None):
        sale = Sale.objects.create(
            salon=self.salon, status=status,
            discount_amount=Decimal("1.00"))
        if day is not None:
            Sale.objects.filter(pk=sale.pk).update(
                created_at=self._at(day))
            sale.refresh_from_db()
        return sale

    def _mixed(self):
        completed = self._sale(Sale.Status.COMPLETED, self.day)
        voided = self._sale(Sale.Status.VOIDED, self.day)
        open_ = self._sale(Sale.Status.OPEN, self.next)
        completed_next = self._sale(Sale.Status.COMPLETED, self.next)
        return completed, voided, open_, completed_next

    def test_default_none_is_unfiltered(self):
        sales = self._mixed()
        self.assertEqual(
            [r["id"] for r in export_sales(self.salon)],
            [s.pk for s in sales])
        self.assertEqual(
            export_sales(self.salon, status=None),
            export_sales(self.salon))
        self.assertEqual(
            export_sales_csv(self.salon, status=None),
            export_sales_csv(self.salon))

    def test_status_exact_stored_value(self):
        completed, voided, open_, completed_next = self._mixed()
        self.assertEqual(
            [r["id"] for r in export_sales(
                self.salon, status=Sale.Status.COMPLETED)],
            [completed.pk, completed_next.pk])
        self.assertEqual(
            [r["id"] for r in export_sales(
                self.salon, status="voided")], [voided.pk])
        self.assertEqual(
            [r["id"] for r in export_sales(
                self.salon, status=Sale.Status.OPEN)], [open_.pk])
        # Exact matching: case variants and unknown values match none.
        self.assertEqual(export_sales(self.salon, status="COMPLETED"), [])
        self.assertEqual(export_sales(self.salon, status="nope"), [])

    def test_status_composes_with_date_window(self):
        completed, voided, open_, completed_next = self._mixed()
        self.assertEqual(
            [r["id"] for r in export_sales(
                self.salon, self.day, self.day,
                status=Sale.Status.COMPLETED)], [completed.pk])
        self.assertEqual(
            [r["id"] for r in export_sales(
                self.salon, self.day, self.next,
                status=Sale.Status.VOIDED)], [voided.pk])
        self.assertEqual(
            export_sales(self.salon, self.next, self.next,
                         status=Sale.Status.VOIDED), [])

    def test_csv_twin_agrees_and_header_only_when_empty(self):
        self._mixed()
        self.assertEqual(
            export_sales_csv(self.salon, status="voided"),
            export_sales_csv(self.salon, status=Sale.Status.VOIDED))
        text = export_sales_csv(
            self.salon, self.day, self.day, status="completed")
        lines = text.strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("completed", lines[1])
        self.assertEqual(
            export_sales_csv(self.salon, status="nope"),
            ",".join(SALE_EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(export_sales(None, status="completed"), [])
        self.assertEqual(
            export_sales_csv(None, status="completed"),
            ",".join(SALE_EXPORT_FIELDNAMES) + "\n")

    def test_read_only(self):
        self._mixed()
        export_sales(self.salon, status="completed")
        export_sales_csv(self.salon, status="voided")
        self.assertEqual(Sale.objects.count(), 4)
