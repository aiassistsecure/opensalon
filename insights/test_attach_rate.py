import csv
import io
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.attach_export import (
    ATTACH_RATE_FIELDNAMES, export_attach_rate_csv,
)
from insights.attach_rate import retail_attach_rate
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
END = date(2026, 11, 8)


class RetailAttachRateTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")

    def _sale(self, day, lines, salon=None, status=Sale.Status.COMPLETED):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=status)
        stamp = datetime(day.year, day.month, day.day, 12, 0,
                         tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        for kind, price, qty, disc in lines:
            SaleItem.objects.create(
                sale=sale, kind=kind, quantity=qty,
                unit_price=Decimal(price),
                discount_amount=Decimal(disc))
        return sale

    def _seed(self):
        S, P, R = (SaleItem.Kind.SERVICE, SaleItem.Kind.PRODUCT,
                   SaleItem.Kind.SERIES)
        # Attached: service 100 + retail 20x2 less 5 discount = 35.
        self._sale(END, [(S, "100.00", 1, "0"), (P, "20.00", 2, "5.00")])
        # Attached: service 80 + retail 10.
        self._sale(END, [(S, "80.00", 1, "0"), (P, "10.00", 1, "0")])
        # Unattached service sales (one with a series line only).
        self._sale(date(2026, 11, 7), [(S, "60.00", 1, "0")])
        self._sale(date(2026, 11, 7),
                   [(S, "50.00", 1, "0"), (R, "200.00", 1, "0")])
        # Product-only sale: retail counts in total only.
        self._sale(END, [(P, "30.00", 1, "0")])

    def test_attach_rate_and_revenue_per_service_sale(self):
        self._seed()
        r = retail_attach_rate(self.salon, days=7, end_date=END)
        self.assertEqual(r.start_date, date(2026, 11, 2))
        self.assertEqual(r.service_sales, 4)
        self.assertEqual(r.attached_sales, 2)
        self.assertEqual(r.unattached_service_sales, 2)
        self.assertEqual(r.product_only_sales, 1)
        self.assertEqual(r.total_completed_sales, 5)
        self.assertEqual(r.attach_rate, Decimal("0.5000"))
        self.assertEqual(r.attach_rate_percent, Decimal("50.00"))
        self.assertEqual(r.service_revenue, Decimal("290.00"))
        self.assertEqual(r.retail_revenue, Decimal("45.00"))
        self.assertEqual(r.total_retail_revenue, Decimal("75.00"))
        self.assertEqual(r.retail_quantity, 3)
        self.assertEqual(
            r.retail_revenue_per_service_sale, Decimal("11.25"))
        self.assertEqual(
            r.retail_revenue_per_attached_sale, Decimal("22.50"))

    def test_daily_breakdown_reconciles(self):
        self._seed()
        r = retail_attach_rate(self.salon, days=7, end_date=END)
        self.assertEqual(len(r.daily), 7)
        self.assertEqual(
            sum(d.service_sales for d in r.daily), r.service_sales)
        self.assertEqual(
            sum(d.attached_sales for d in r.daily), r.attached_sales)
        self.assertEqual(
            sum((d.retail_revenue for d in r.daily), Decimal("0.00")),
            r.retail_revenue)
        last = r.daily[-1]
        self.assertEqual(
            (last.service_sales, last.attached_sales), (2, 2))
        self.assertEqual(last.attach_rate, Decimal("1.0000"))

    def test_excludes_open_voided_other_salon_and_outside_window(self):
        S, P = SaleItem.Kind.SERVICE, SaleItem.Kind.PRODUCT
        lines = [(S, "100.00", 1, "0"), (P, "20.00", 1, "0")]
        self._sale(END, lines, status=Sale.Status.OPEN)
        self._sale(END, lines, status=Sale.Status.VOIDED)
        self._sale(END, lines, salon=self.other)
        self._sale(date(2026, 10, 1), lines)  # before 7-day window
        self._sale(END, [(S, "100.00", 1, "0")])
        r = retail_attach_rate(self.salon, days=7, end_date=END)
        self.assertEqual(r.service_sales, 1)
        self.assertEqual(r.attached_sales, 0)
        self.assertEqual(r.attach_rate, Decimal("0.0000"))
        self.assertEqual(r.retail_revenue, Decimal("0.00"))

    def test_zero_window_and_no_sales_never_divide_by_zero(self):
        r = retail_attach_rate(self.salon, days=7, end_date=END)
        self.assertEqual(r.service_sales, 0)
        self.assertEqual(r.attach_rate, Decimal("0.0000"))
        self.assertEqual(
            r.retail_revenue_per_service_sale, Decimal("0.00"))
        self.assertEqual(
            r.retail_revenue_per_attached_sale, Decimal("0.00"))
        empty = retail_attach_rate(self.salon, days=0, end_date=END)
        self.assertEqual(empty.daily, ())
        self.assertEqual(empty.total_completed_sales, 0)

    def test_export_rows_match_service(self):
        self._seed()
        text = export_attach_rate_csv(self.salon, days=7, end_date=END)
        self.assertEqual(
            list(csv.reader(io.StringIO(text)))[0],
            ATTACH_RATE_FIELDNAMES)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 1)
        r = retail_attach_rate(self.salon, days=7, end_date=END)
        row = rows[0]
        self.assertEqual(row["service_sales"], str(r.service_sales))
        self.assertEqual(row["attached_sales"], str(r.attached_sales))
        self.assertEqual(row["attach_rate"], "0.5000")
        self.assertEqual(row["attach_rate_percent"], "50.00")
        self.assertEqual(row["retail_revenue"], "45.00")
        self.assertEqual(
            row["retail_revenue_per_service_sale"], "11.25")
        self.assertEqual(row["start_date"], r.start_date.isoformat())
        with self.assertRaises(TypeError):
            export_attach_rate_csv(
                self.salon, days=7, end_date=END, today=END)
