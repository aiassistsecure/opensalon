import csv
import datetime
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale, SaleItem
from checkout.void import void_sale
from checkout.void_export import (
    EXPORT_FIELDNAMES,
    export_voided_sales,
    export_voided_sales_csv,
    void_export_row,
)
from saloncore.models import Salon


class VoidExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)

    def _at(self, day, hour=12, minute=0):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, minute)),
            datetime.timezone.utc,
        )

    def _voided_sale(self, day=None, hour=12, minute=0, price="85.00",
                     reason="entered in error", salon=None):
        sale = Sale.objects.create(
            salon=salon or self.salon,
            status=Sale.Status.COMPLETED,
            completed_at=self._at(day or self.day, hour=hour),
        )
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal(price),
        )
        void_sale(sale, reason)
        Sale.objects.filter(pk=sale.pk).update(
            voided_at=self._at(day or self.day, hour=hour, minute=minute)
        )
        sale.refresh_from_db()
        return sale

    def _completed_sale(self, salon=None, price="50.00"):
        sale = Sale.objects.create(
            salon=salon or self.salon,
            status=Sale.Status.COMPLETED,
            completed_at=self._at(self.day),
        )
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal(price),
        )
        return sale

    def test_header_and_columns(self):
        csv_text = export_voided_sales_csv(self.salon, self.day, self.day)
        # Header present even before data checks; verify exact columns.
        self.assertEqual(
            EXPORT_FIELDNAMES,
            ["id", "sale_id", "salon_id", "client_id", "status",
             "created_at", "completed_at", "voided_at", "void_reason",
             "total"],
        )
        sale = self._voided_sale(reason="rung up twice", price="85.5")
        rows = export_voided_sales(self.salon, self.day, self.day)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(list(row), EXPORT_FIELDNAMES)
        self.assertEqual(row["id"], sale.pk)
        self.assertEqual(row["sale_id"], sale.pk)
        self.assertEqual(row["salon_id"], self.salon.pk)
        self.assertIsNone(row["client_id"])
        self.assertEqual(row["status"], "voided")
        self.assertEqual(row["voided_at"], sale.voided_at.isoformat())
        self.assertEqual(row["void_reason"], "rung up twice")
        self.assertEqual(row["total"], "85.50")
        self.assertEqual(void_export_row(sale), row)
        parsed = list(csv.DictReader(io.StringIO(
            export_voided_sales_csv(self.salon, self.day, self.day))))
        self.assertEqual(len(parsed), 1)
        for key in EXPORT_FIELDNAMES:
            expected = "" if row[key] is None else str(row[key])
            self.assertEqual(parsed[0][key], expected)
        header = export_voided_sales_csv(
            self.salon, self.day, self.day).splitlines()[0]
        self.assertEqual(header, ",".join(EXPORT_FIELDNAMES))

    def test_only_voided_sales_included(self):
        voided = self._voided_sale()
        self._completed_sale()
        Sale.objects.create(salon=self.salon, status=Sale.Status.OPEN)
        rows = export_voided_sales(self.salon, self.day, self.day)
        self.assertEqual([r["id"] for r in rows], [voided.pk])

    def test_salon_isolation(self):
        own = self._voided_sale()
        self._voided_sale(salon=self.other)
        rows = export_voided_sales(self.salon, self.day, self.day)
        self.assertEqual([r["id"] for r in rows], [own.pk])
        csv_text = export_voided_sales_csv(self.salon, self.day)
        self.assertEqual(len(csv_text.strip().splitlines()), 2)

    def test_empty_is_header_only(self):
        self._voided_sale()
        empty_from = self.day + datetime.timedelta(days=10)
        empty_to = self.day + datetime.timedelta(days=11)
        self.assertEqual(
            export_voided_sales(self.salon, empty_from, empty_to), [])
        self.assertEqual(
            export_voided_sales_csv(self.salon, empty_from, empty_to),
            ",".join(EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(
            export_voided_sales(self.salon, empty_to, empty_from), [])
        self.assertEqual(
            export_voided_sales_csv(self.salon, empty_to, empty_from),
            ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_range_on_voided_at_and_chronological(self):
        before = self._voided_sale(
            day=self.day - datetime.timedelta(days=1))
        first = self._voided_sale()
        second = self._voided_sale(
            day=self.day + datetime.timedelta(days=1))
        after = self._voided_sale(
            day=self.day + datetime.timedelta(days=2))
        rows = export_voided_sales(
            self.salon, self.day, self.day + datetime.timedelta(days=1))
        self.assertEqual([r["id"] for r in rows], [first.pk, second.pk])
        self.assertNotIn(before.pk, [r["id"] for r in rows])
        self.assertNotIn(after.pk, [r["id"] for r in rows])

    def test_export_is_read_only(self):
        sale = self._voided_sale()
        export_voided_sales(self.salon, self.day, self.day)
        export_voided_sales_csv(self.salon, self.day, self.day)
        self.assertEqual(Sale.objects.count(), 1)
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.VOIDED)
        self.assertEqual(sale.void_reason, "entered in error")
