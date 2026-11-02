import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from checkout.models import Payment, Refund, Sale, SaleItem
from checkout.refund_report import refund_totals
from checkout.refunds import record_refund
from insights.refunds_net import refunds_net_revenue
from insights.refunds_net_export import (
    REFUNDS_NET_FIELDNAMES,
    export_refunds_net_csv,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


class RefundsNetTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")

    def _sale(self, day, price="100.00", salon=None, status=None):
        sale = Sale.objects.create(
            salon=salon or self.salon,
            status=status or Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal(price))
        Payment.objects.create(
            sale=sale, method=Payment.Method.CASH,
            amount=Decimal(price), status=Payment.Status.COMPLETED)
        sale.refresh_from_db()
        return sale

    def _refund(self, sale, amount, day):
        refund = record_refund(sale, Decimal(amount))
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Refund.objects.filter(pk=refund.pk).update(created_at=stamp)
        return refund

    def test_gross_refunds_net_math(self):
        sale = self._sale(date(2026, 11, 5), "200.00")
        self._sale(date(2026, 11, 6), "50.00")
        self._refund(sale, "20.00", date(2026, 11, 5))
        self._refund(sale, "15.00", date(2026, 11, 7))
        r = refunds_net_revenue(self.salon, START, END)
        self.assertEqual(r.gross, Decimal("250.00"))
        self.assertEqual(r.gross_revenue, Decimal("250.00"))
        self.assertEqual(r.refunds, Decimal("35.00"))
        self.assertEqual(r.refund_total, Decimal("35.00"))
        self.assertEqual(r.net, Decimal("215.00"))
        self.assertEqual(r.net_revenue, Decimal("215.00"))
        self.assertEqual(r.refund_count, 2)
        self.assertEqual((r.start_date, r.end_date, r.days), (START, END, 7))
        # Figures match the owning services verbatim.
        self.assertEqual(r.refunds,
                         refund_totals(self.salon, START, END).total)

    def test_refund_attributed_to_refund_day_not_sale_day(self):
        sale = self._sale(START - timedelta(days=10), "100.00")
        self._refund(sale, "40.00", date(2026, 11, 5))
        r = refunds_net_revenue(self.salon, START, END)
        self.assertEqual(r.gross, Decimal("0.00"))
        self.assertEqual(r.refunds, Decimal("40.00"))
        self.assertEqual(r.net, Decimal("-40.00"))

    def test_refund_outside_window_excluded(self):
        sale = self._sale(date(2026, 11, 5), "100.00")
        self._refund(sale, "30.00", END + timedelta(days=1))
        r = refunds_net_revenue(self.salon, START, END)
        self.assertEqual(
            (r.gross, r.refunds, r.net, r.refund_count),
            (Decimal("100.00"), Decimal("0.00"),
             Decimal("100.00"), 0))

    def test_empty_window_is_zeroes(self):
        r = refunds_net_revenue(self.salon, START, END)
        self.assertEqual(
            (r.gross, r.refunds, r.net, r.refund_count),
            (Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), 0))

    def test_salon_scoping_and_unsettled_sales_excluded(self):
        self._sale(date(2026, 11, 5), "999.00", salon=self.other)
        self._sale(date(2026, 11, 5), "999.00",
                   status=Sale.Status.VOIDED)
        self._sale(date(2026, 11, 5), "999.00", status=Sale.Status.OPEN)
        self._sale(date(2026, 11, 5), "80.00")
        r = refunds_net_revenue(self.salon, START, END)
        self.assertEqual(r.gross, Decimal("80.00"))

    def test_non_seven_day_window(self):
        self._sale(date(2026, 11, 7), "30.00")
        r = refunds_net_revenue(
            self.salon, date(2026, 11, 6), date(2026, 11, 8))
        self.assertEqual((r.gross, r.days), (Decimal("30.00"), 3))

    def test_reversed_window_raises(self):
        with self.assertRaises(ValueError):
            refunds_net_revenue(self.salon, END, START)
        with self.assertRaises(ValueError):
            export_refunds_net_csv(self.salon, END, START)


class RefundsNetExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")

    def test_header_and_export_matches_service(self):
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal("120.00"))
        text = export_refunds_net_csv(self.salon, START, END)
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, REFUNDS_NET_FIELDNAMES)
        row = list(csv.DictReader(io.StringIO(text)))[0]
        result = refunds_net_revenue(self.salon, START, END)
        self.assertEqual(Decimal(row["gross_revenue"]), result.gross)
        self.assertEqual(Decimal(row["refund_total"]), result.refunds)
        self.assertEqual(Decimal(row["net_revenue"]), result.net)
        self.assertEqual(row["gross_revenue"], "120.00")
        self.assertEqual(row["start_date"], START.isoformat())
