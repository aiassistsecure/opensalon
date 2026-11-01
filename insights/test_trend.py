from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.trend import RevenueTrend, TrendDay, daily_revenue_trend
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
END = date(2026, 11, 8)  # Sunday


class DailyRevenueTrendTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")

    def _sale(self, *, day_offset=0, salon=None, status=Sale.Status.COMPLETED,
              completed=True):
        sale = Sale.objects.create(salon=salon or self.salon, status=status)
        stamp = datetime(2026, 11, 8, 12, 0, tzinfo=UTC) - timedelta(
            days=day_offset
        )
        updates = {"created_at": stamp}
        if completed:
            updates["completed_at"] = stamp
        Sale.objects.filter(pk=sale.pk).update(**updates)
        sale.refresh_from_db()
        return sale

    def _item(self, sale, kind, price, quantity=1):
        return SaleItem.objects.create(
            sale=sale, kind=kind, quantity=quantity,
            unit_price=Decimal(price),
        )

    def test_zero_fill_default_14_days_ending_on_end_date(self):
        result = daily_revenue_trend(self.salon, end_date=END)
        self.assertIsInstance(result, RevenueTrend)
        self.assertEqual(len(result), 14)
        self.assertEqual(len(result.days), 14)
        self.assertEqual(result.start_date, END - timedelta(days=13))
        self.assertEqual(result.end_date, END)
        self.assertEqual(result[0].date, END - timedelta(days=13))
        self.assertEqual(result[-1].date, END)
        for entry in result:
            self.assertIsInstance(entry, TrendDay)
            self.assertEqual(entry.service, Decimal("0.00"))
            self.assertEqual(entry.retail, Decimal("0.00"))
            self.assertEqual(entry.series, Decimal("0.00"))
            self.assertEqual(entry.series_revenue, Decimal("0.00"))
            self.assertEqual(entry.total, Decimal("0.00"))
            self.assertEqual(entry.moving_average_7d, Decimal("0.00"))

    def test_split_correctness_per_day_with_quantities(self):
        today_sale = self._sale(day_offset=0)
        self._item(today_sale, SaleItem.Kind.SERVICE, "85.00")
        self._item(today_sale, SaleItem.Kind.PRODUCT, "24.00", quantity=2)
        yesterday = self._sale(day_offset=1)
        self._item(yesterday, SaleItem.Kind.SERVICE, "50.00")
        result = daily_revenue_trend(self.salon, days=3, end_date=END)
        self.assertEqual([e.date for e in result],
                         [END - timedelta(days=2), END - timedelta(days=1), END])
        self.assertEqual(result[-1].service, Decimal("85.00"))
        self.assertEqual(result[-1].retail, Decimal("48.00"))
        self.assertEqual(result[-1].total, Decimal("133.00"))
        self.assertEqual(result[1].service, Decimal("50.00"))
        self.assertEqual(result[1].total, Decimal("50.00"))
        self.assertEqual(result[0].total, Decimal("0.00"))

    def test_series_included_in_total_and_moving_average(self):
        sale = self._sale(day_offset=0)
        self._item(sale, SaleItem.Kind.SERIES, "150.00", quantity=2)
        self._item(sale, SaleItem.Kind.SERIES, "50.00")
        self._item(sale, SaleItem.Kind.SERVICE, "10.00")
        result = daily_revenue_trend(self.salon, days=2, end_date=END)
        self.assertEqual(result[-1].series, Decimal("350.00"))
        self.assertEqual(result[-1].total, Decimal("360.00"))
        self.assertEqual(
            result[-1].total,
            result[-1].service + result[-1].retail + result[-1].series,
        )
        self.assertEqual(result[-1].moving_average_7d, Decimal("180.00"))
        self.assertEqual(result[0].series, Decimal("0.00"))

    def test_series_only_sale_counts_toward_series_and_total(self):
        sale = self._sale(day_offset=0)
        self._item(sale, SaleItem.Kind.SERIES, "200.00")
        result = daily_revenue_trend(self.salon, days=1, end_date=END)
        self.assertEqual(result[0].series, Decimal("200.00"))
        self.assertEqual(result[0].total, Decimal("200.00"))

    def test_voided_and_open_sales_excluded(self):
        for status in (Sale.Status.VOIDED, Sale.Status.OPEN):
            sale = self._sale(status=status)
            self._item(sale, SaleItem.Kind.SERVICE, "999.00")
        completed = self._sale()
        self._item(completed, SaleItem.Kind.SERVICE, "40.00")
        result = daily_revenue_trend(self.salon, days=3, end_date=END)
        self.assertEqual(result[-1].total, Decimal("40.00"))
        self.assertEqual(sum(e.total for e in result), Decimal("40.00"))

    def test_moving_average_uses_trailing_seven_days(self):
        for offset in range(7):  # 10.00 on each of the last 7 days
            sale = self._sale(day_offset=offset)
            self._item(sale, SaleItem.Kind.SERVICE, "10.00")
        result = daily_revenue_trend(self.salon, days=7, end_date=END)
        self.assertEqual(result[0].moving_average_7d, Decimal("10.00"))
        self.assertEqual(result[-1].moving_average_7d, Decimal("10.00"))
        # Single 70.00 day on the other salon: 0.00, then (0+70)/2.
        sale = self._sale(salon=self.other)
        self._item(sale, SaleItem.Kind.SERVICE, "70.00")
        result2 = daily_revenue_trend(self.other, days=2, end_date=END)
        self.assertEqual(result2[0].moving_average_7d, Decimal("0.00"))
        self.assertEqual(result2[1].moving_average_7d, Decimal("35.00"))

    def test_window_excludes_older_and_other_salon(self):
        old = self._sale(day_offset=14)
        self._item(old, SaleItem.Kind.SERVICE, "999.00")
        other = self._sale(salon=self.other)
        self._item(other, SaleItem.Kind.SERVICE, "999.00")
        edge = self._sale(day_offset=13)
        self._item(edge, SaleItem.Kind.SERVICE, "25.00")
        result = daily_revenue_trend(self.salon, end_date=END)
        self.assertEqual(result[0].total, Decimal("25.00"))
        self.assertEqual(sum(e.total for e in result), Decimal("25.00"))

    def test_completed_sale_without_completed_at_uses_created_at(self):
        sale = self._sale(completed=False)
        Sale.objects.filter(pk=sale.pk).update(completed_at=None)
        self._item(sale, SaleItem.Kind.PRODUCT, "30.00")
        result = daily_revenue_trend(self.salon, days=3, end_date=END)
        self.assertEqual(result[-1].retail, Decimal("30.00"))

    def test_non_positive_days_returns_empty(self):
        self.assertEqual(
            len(daily_revenue_trend(self.salon, days=0, end_date=END)), 0
        )
