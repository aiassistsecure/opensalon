import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.rollup import (
    monthly_revenue_rollup, revenue_rollup, weekly_revenue_rollup,
)
from insights.rollup_export import ROLLUP_FIELDNAMES, export_rollup_csv
from insights.trend import daily_revenue_trend
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
END = date(2026, 11, 8)  # Sunday; ISO week Mon 2026-11-02..Sun 11-08


class RevenueRollupTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")

    def _sale_on(self, day, kind, price, salon=None, quantity=1):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(sale=sale, kind=kind, quantity=quantity,
                                unit_price=Decimal(price))
        return sale

    def _seed_two_weeks(self):
        self._sale_on(date(2026, 10, 26), SaleItem.Kind.SERVICE, "100.00")
        self._sale_on(date(2026, 10, 28), SaleItem.Kind.PRODUCT, "20.00")
        self._sale_on(date(2026, 11, 1), SaleItem.Kind.SERIES, "50.00")
        self._sale_on(date(2026, 11, 2), SaleItem.Kind.SERVICE, "85.00")
        self._sale_on(date(2026, 11, 8), SaleItem.Kind.PRODUCT, "24.00",
                      quantity=2)
        self._sale_on(date(2026, 11, 8), SaleItem.Kind.SERIES, "30.00")

    def _assert_buckets_reconcile(self, buckets, trend):
        self.assertEqual(
            sum((b.total for b in buckets), Decimal("0.00")),
            sum((e.total for e in trend), Decimal("0.00")))
        for bucket in buckets:
            members = [e for e in trend
                       if bucket.start_date <= e.date <= bucket.end_date]
            self.assertEqual(list(bucket.days), members)
            self.assertEqual(bucket.day_count, len(members))
            for field in ("service", "retail", "series", "total"):
                self.assertEqual(
                    getattr(bucket, field),
                    sum((getattr(e, field) for e in members),
                        Decimal("0.00")))
            self.assertEqual(
                bucket.total,
                bucket.service + bucket.retail + bucket.series)

    def test_week_sums_equal_sum_of_member_days(self):
        self._seed_two_weeks()
        trend = daily_revenue_trend(self.salon, days=14, end_date=END)
        weeks = weekly_revenue_rollup(self.salon, days=14, end_date=END)
        self.assertEqual(len(weeks), 2)
        self.assertEqual([w.label for w in weeks],
                         ["2026-W44", "2026-W45"])
        self.assertEqual([w.day_count for w in weeks], [7, 7])
        self.assertEqual(weeks[0].start_date, date(2026, 10, 26))
        self.assertEqual(weeks[0].end_date, date(2026, 11, 1))
        self.assertEqual(weeks[0].total, Decimal("170.00"))
        self.assertEqual(weeks[1].service, Decimal("85.00"))
        self.assertEqual(weeks[1].retail, Decimal("48.00"))
        self.assertEqual(weeks[1].series, Decimal("30.00"))
        self.assertEqual(weeks[1].total, Decimal("163.00"))
        self._assert_buckets_reconcile(weeks, trend)

    def test_partial_week_at_window_edge(self):
        self._sale_on(date(2026, 11, 4), SaleItem.Kind.SERVICE, "60.00")
        self._sale_on(END, SaleItem.Kind.SERVICE, "40.00")
        trend = daily_revenue_trend(self.salon, days=5, end_date=END)
        weeks = weekly_revenue_rollup(self.salon, days=5, end_date=END)
        self.assertEqual(len(weeks), 1)
        self.assertEqual(weeks[0].label, "2026-W45")
        self.assertEqual(weeks[0].day_count, 5)
        self.assertEqual(weeks[0].start_date, date(2026, 11, 4))
        self.assertEqual(weeks[0].end_date, END)
        self.assertEqual(weeks[0].total, Decimal("100.00"))
        self._assert_buckets_reconcile(weeks, trend)
        # 10-day window: partial 3-day first week + full second week.
        weeks10 = weekly_revenue_rollup(self.salon, days=10, end_date=END)
        self.assertEqual([w.day_count for w in weeks10], [3, 7])
        self.assertEqual(weeks10[0].start_date, date(2026, 10, 30))

    def test_month_sums_equal_sum_of_member_days(self):
        self._sale_on(date(2026, 10, 20), SaleItem.Kind.SERVICE, "70.00")
        self._sale_on(date(2026, 10, 31), SaleItem.Kind.PRODUCT, "10.00")
        self._sale_on(date(2026, 11, 1), SaleItem.Kind.SERIES, "200.00")
        self._sale_on(END, SaleItem.Kind.SERVICE, "15.00")
        trend = daily_revenue_trend(self.salon, days=20, end_date=END)
        months = monthly_revenue_rollup(self.salon, days=20, end_date=END)
        self.assertEqual([m.label for m in months], ["2026-10", "2026-11"])
        self.assertEqual([m.day_count for m in months], [12, 8])
        self.assertEqual(months[0].start_date, date(2026, 10, 20))
        self.assertEqual(months[0].total, Decimal("80.00"))
        self.assertEqual(months[1].end_date, END)
        self.assertEqual(months[1].total, Decimal("215.00"))
        self._assert_buckets_reconcile(months, trend)

    def test_zero_fill_and_salon_scoping_and_bad_granularity(self):
        self._sale_on(END, SaleItem.Kind.SERVICE, "999.00",
                      salon=self.other)
        weeks = weekly_revenue_rollup(self.salon, days=7, end_date=END)
        self.assertEqual(len(weeks), 1)
        self.assertEqual(weeks[0].total, Decimal("0.00"))
        self.assertEqual(revenue_rollup(
            self.salon, "month", days=7, end_date=END)[0].total,
            Decimal("0.00"))
        self.assertEqual(len(revenue_rollup(
            self.salon, days=0, end_date=END)), 0)
        with self.assertRaises(ValueError):
            revenue_rollup(self.salon, "quarter", days=7, end_date=END)

    def test_export_rows_match_service(self):
        self._seed_two_weeks()
        text = export_rollup_csv(self.salon, days=14, end_date=END)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         ROLLUP_FIELDNAMES)
        weeks = weekly_revenue_rollup(self.salon, days=14, end_date=END)
        self.assertEqual(len(rows), len(weeks))
        for row, week in zip(rows, weeks):
            self.assertEqual(row["label"], week.label)
            self.assertEqual(row["period_start"], week.start_date.isoformat())
            self.assertEqual(row["period_end"], week.end_date.isoformat())
            self.assertEqual(row["day_count"], str(week.day_count))
            self.assertEqual(row["total"], str(week.total))
        monthly = export_rollup_csv(
            self.salon, granularity="month", days=14, end_date=END)
        self.assertEqual(
            [r["label"] for r in csv.DictReader(io.StringIO(monthly))],
            ["2026-10", "2026-11"])

    def test_command_stdout_matches_export_service(self):
        out = io.StringIO()
        call_command("export_rollup", salon_id=self.salon.pk, days=14,
                     end_date=END, stdout=out)
        self.assertEqual(out.getvalue(), export_rollup_csv(
            self.salon, granularity="week", days=14, end_date=END))
        with self.assertRaises(CommandError):
            call_command("export_rollup", salon_id=self.salon.pk + 999,
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_rollup", salon_id=self.salon.pk,
                         granularity="quarter", stdout=io.StringIO())
