import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.discounts import discounts_report
from insights.discounts_export import (
    DISCOUNTS_FIELDNAMES,
    export_discounts_csv,
)
from insights.prior_period import _split_for_window
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


class DiscountsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")

    def _sale(self, day, price="100.00", salon=None, status=None,
              sale_discount="0.00", item_discount="0.00",
              completed=True):
        sale = Sale.objects.create(
            salon=salon or self.salon,
            status=status or Sale.Status.COMPLETED,
            discount_amount=Decimal(sale_discount))
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp,
            completed_at=stamp if completed else None)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal(price),
            discount_amount=Decimal(item_discount))
        sale.refresh_from_db()
        return sale

    def test_discount_total_and_share_math(self):
        self._sale(date(2026, 11, 5), "200.00",
                   sale_discount="10.00", item_discount="15.00")
        self._sale(date(2026, 11, 6), "50.00", item_discount="5.00")
        r = discounts_report(self.salon, START, END)
        self.assertEqual(r.gross, Decimal("250.00"))
        self.assertEqual(r.gross_revenue, Decimal("250.00"))
        self.assertEqual(r.discount_total, Decimal("30.00"))
        self.assertEqual(r.discounts_total, Decimal("30.00"))
        self.assertEqual(r.discount_share_percent, Decimal("12.00"))
        self.assertEqual(r.discount_share, Decimal("12.00"))
        self.assertEqual((r.start_date, r.end_date, r.days), (START, END, 7))
        # Gross is the owning split service's figure verbatim.
        self.assertEqual(
            r.gross, _split_for_window(self.salon, START, END).total)

    def test_empty_window_zeroes_and_none_share(self):
        r = discounts_report(self.salon, START, END)
        self.assertEqual(r.gross, Decimal("0.00"))
        self.assertEqual(r.discount_total, Decimal("0.00"))
        self.assertIsNone(r.discount_share_percent)

    def test_no_discounts_share_is_zero_not_none(self):
        self._sale(date(2026, 11, 5), "100.00")
        r = discounts_report(self.salon, START, END)
        self.assertEqual(r.discount_share_percent, Decimal("0.00"))

    def test_salon_scoping_and_unsettled_sales_excluded(self):
        self._sale(date(2026, 11, 5), "999.00", salon=self.other,
                   item_discount="99.00")
        self._sale(date(2026, 11, 5), "999.00",
                   status=Sale.Status.VOIDED, item_discount="99.00")
        self._sale(date(2026, 11, 5), "999.00",
                   status=Sale.Status.OPEN, item_discount="99.00")
        self._sale(date(2026, 11, 5), "80.00", item_discount="8.00")
        r = discounts_report(self.salon, START, END)
        self.assertEqual(
            (r.gross, r.discount_total), (Decimal("80.00"), Decimal("8.00")))

    def test_attribution_completed_at_else_created_at(self):
        # Created before the window but completed inside: counts.
        sale = self._sale(START - timedelta(days=10), "100.00",
                          item_discount="10.00")
        inside = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(completed_at=inside)
        # Completed after the window, created inside: excluded.
        sale2 = self._sale(date(2026, 11, 5), "100.00",
                           item_discount="10.00")
        Sale.objects.filter(pk=sale2.pk).update(
            completed_at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC))
        # No completed_at: created_at decides.
        self._sale(date(2026, 11, 6), "50.00", item_discount="5.00",
                   completed=False)
        self._sale(END + timedelta(days=1), "50.00",
                   item_discount="5.00", completed=False)
        r = discounts_report(self.salon, START, END)
        self.assertEqual(
            (r.gross, r.discount_total),
            (Decimal("150.00"), Decimal("15.00")))

    def test_non_seven_day_window(self):
        self._sale(date(2026, 11, 7), "30.00", item_discount="3.00")
        start, end = date(2026, 11, 6), date(2026, 11, 8)
        r = discounts_report(self.salon, start, end)
        # Gross stays verbatim from _split_for_window for any length.
        self.assertEqual(r.gross, _split_for_window(self.salon, start, end).total)
        self.assertEqual((r.discount_total, r.days), (Decimal("3.00"), 3))

    def test_reversed_window_raises(self):
        with self.assertRaises(ValueError):
            discounts_report(self.salon, END, START)
        with self.assertRaises(ValueError):
            export_discounts_csv(self.salon, END, START)


class DiscountsExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")

    def test_header_and_export_matches_service(self):
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED,
            discount_amount=Decimal("2.00"))
        stamp = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal("120.00"),
            discount_amount=Decimal("10.00"))
        text = export_discounts_csv(self.salon, START, END)
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, DISCOUNTS_FIELDNAMES)
        row = list(csv.DictReader(io.StringIO(text)))[0]
        result = discounts_report(self.salon, START, END)
        self.assertEqual(Decimal(row["gross_revenue"]), result.gross)
        self.assertEqual(Decimal(row["discount_total"]),
                         result.discount_total)
        self.assertEqual(Decimal(row["discount_share_percent"]),
                         result.discount_share_percent)
        self.assertEqual(row["discount_total"], "12.00")
        self.assertEqual(row["discount_share_percent"], "10.00")
        self.assertEqual(row["start_date"], START.isoformat())

    def test_none_share_renders_empty(self):
        row = list(csv.DictReader(io.StringIO(
            export_discounts_csv(self.salon, START, END))))[0]
        self.assertEqual(row["discount_share_percent"], "")
        self.assertEqual(row["gross_revenue"], "0.00")
