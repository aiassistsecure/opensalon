import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.prior_period import prior_period_revenue_split
from insights.prior_period_export import (
    PRIOR_PERIOD_FIELDNAMES,
    export_prior_period_csv,
)
from insights.services import RevenueSplit, last_7_days_revenue_split
from insights.trend import daily_revenue_trend
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)  # Monday; 7-day window to Nov 8
END = date(2026, 11, 8)


class PriorPeriodTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")

    def _sale(self, day, salon=None):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        sale.refresh_from_db()
        return sale

    def _item(self, sale, kind, price, quantity=1):
        return SaleItem.objects.create(
            sale=sale, kind=kind, quantity=quantity,
            unit_price=Decimal(price))

    def _seed_pair(self):
        cur = self._sale(date(2026, 11, 5))
        self._item(cur, SaleItem.Kind.SERVICE, "100.00")
        self._item(cur, SaleItem.Kind.PRODUCT, "50.00")
        self._item(cur, SaleItem.Kind.SERIES, "200.00")
        prior = self._sale(date(2026, 10, 29))
        self._item(prior, SaleItem.Kind.SERVICE, "50.00")
        self._item(prior, SaleItem.Kind.PRODUCT, "50.00")
        self._item(prior, SaleItem.Kind.SERIES, "100.00")

    def test_equal_length_prior_window_boundaries(self):
        self._seed_pair()
        r = prior_period_revenue_split(self.salon, START, END)
        self.assertEqual((r.current.start_date, r.current.end_date),
                         (START, END))
        self.assertEqual(r.current.days, 7)
        self.assertEqual((r.prior.start_date, r.prior.end_date),
                         (START - timedelta(days=7), START - timedelta(days=1)))
        self.assertEqual(r.prior.days, 7)
        self.assertEqual(r.prior_end_date, date(2026, 11, 1))
        # Boundary days: prior-start and current-start count; the day
        # before the prior window and the day after the current do not.
        self._item(self._sale(date(2026, 10, 26)),
                   SaleItem.Kind.SERVICE, "10.00")
        self._item(self._sale(START), SaleItem.Kind.SERVICE, "20.00")
        self._item(self._sale(date(2026, 10, 25)),
                   SaleItem.Kind.SERVICE, "999.00")
        self._item(self._sale(date(2026, 11, 9)),
                   SaleItem.Kind.SERVICE, "999.00")
        r = prior_period_revenue_split(self.salon, START, END)
        self.assertEqual(r.prior.service, Decimal("60.00"))
        self.assertEqual(r.current.service, Decimal("120.00"))

    def test_delta_math_incl_series(self):
        self._seed_pair()
        r = prior_period_revenue_split(self.salon, START, END)
        self.assertIsInstance(r.current, RevenueSplit)
        self.assertEqual((r.service.current, r.service.prior,
                          r.service.delta, r.service.percent_change),
                         (Decimal("100.00"), Decimal("50.00"),
                          Decimal("50.00"), Decimal("100.00")))
        self.assertEqual((r.retail.delta, r.retail.percent_change),
                         (Decimal("0.00"), Decimal("0.00")))
        self.assertEqual((r.series.current, r.series.prior,
                          r.series.delta, r.series.percent_change),
                         (Decimal("200.00"), Decimal("100.00"),
                          Decimal("100.00"), Decimal("100.00")))
        self.assertEqual((r.total.current, r.total.prior,
                          r.total.delta, r.total.percent_change),
                         (Decimal("350.00"), Decimal("200.00"),
                          Decimal("150.00"), Decimal("75.00")))

    def test_seven_day_current_matches_split_service(self):
        self._seed_pair()
        r = prior_period_revenue_split(self.salon, START, END)
        self.assertEqual(r.current,
                         last_7_days_revenue_split(self.salon, today=END))

    def test_non_seven_day_window_uses_trend_totals(self):
        start, end = date(2026, 11, 6), date(2026, 11, 8)  # 3 days
        self._item(self._sale(end), SaleItem.Kind.SERVICE, "30.00")
        self._item(self._sale(date(2026, 11, 4)),
                   SaleItem.Kind.SERIES, "10.00")
        r = prior_period_revenue_split(self.salon, start, end)
        self.assertEqual((r.prior.start_date, r.prior.end_date),
                         (date(2026, 11, 3), date(2026, 11, 5)))
        trend = daily_revenue_trend(self.salon, days=3, end_date=end)
        self.assertEqual(r.current.total,
                         sum((e.total for e in trend), Decimal("0.00")))
        self.assertEqual(r.current.service, Decimal("30.00"))
        self.assertEqual(r.prior.series, Decimal("10.00"))
        self.assertEqual(r.total.percent_change, Decimal("200.00"))

    def test_zero_prior_period_percent_is_none_never_error(self):
        self._item(self._sale(date(2026, 11, 5)),
                   SaleItem.Kind.SERVICE, "80.00")
        r = prior_period_revenue_split(self.salon, START, END)
        for comp in (r.service, r.retail, r.series, r.total):
            self.assertIsNone(comp.percent_change)
        self.assertEqual(r.service.delta, Decimal("80.00"))
        empty = prior_period_revenue_split(self.other, START, END)
        self.assertEqual(empty.total.delta, Decimal("0.00"))
        self.assertIsNone(empty.total.percent_change)

    def test_salon_scoping(self):
        self._seed_pair()
        self._item(self._sale(date(2026, 11, 5), salon=self.other),
                   SaleItem.Kind.SERVICE, "999.00")
        self._item(self._sale(date(2026, 10, 29), salon=self.other),
                   SaleItem.Kind.SERVICE, "999.00")
        r = prior_period_revenue_split(self.salon, START, END)
        self.assertEqual(r.total.current, Decimal("350.00"))
        self.assertEqual(r.total.prior, Decimal("200.00"))
        other = prior_period_revenue_split(self.other, START, END)
        self.assertEqual(other.total.current, Decimal("999.00"))

    def test_reversed_window_raises(self):
        with self.assertRaises(ValueError):
            prior_period_revenue_split(self.salon, END, START)


class PriorPeriodExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")

    def _rows(self, **kwargs):
        text = export_prior_period_csv(self.salon, START, END, **kwargs)
        return text, list(csv.DictReader(io.StringIO(text)))

    def test_header_and_export_matches_service(self):
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(sale=sale, kind=SaleItem.Kind.SERIES,
                                quantity=1, unit_price=Decimal("120.00"))
        text, rows = self._rows()
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, PRIOR_PERIOD_FIELDNAMES)
        self.assertEqual([r["component"] for r in rows],
                         ["service", "retail", "series", "total"])
        result = prior_period_revenue_split(self.salon, START, END)
        for row in rows:
            comp = getattr(result, row["component"])
            self.assertEqual(Decimal(row["current"]), comp.current)
            self.assertEqual(Decimal(row["prior"]), comp.prior)
            self.assertEqual(Decimal(row["delta"]), comp.delta)
            self.assertEqual(row["current_start_date"], START.isoformat())
            self.assertEqual(row["prior_end_date"], "2026-11-01")
        series = rows[2]
        self.assertEqual(series["current"], "120.00")
        # Zero prior -> percent renders empty, never an error.
        self.assertEqual(series["percent_change"], "")
