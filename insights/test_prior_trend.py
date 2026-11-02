import csv, io, os, tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.prior_trend import prior_trend
from insights.prior_trend_export import (
    PRIOR_TREND_FIELDNAMES, export_prior_trend, export_prior_trend_csv)
from insights.trend import daily_revenue_trend
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START, END = date(2026, 11, 2), date(2026, 11, 8)  # Monday..Sunday
PRIOR_START, PRIOR_END = START - timedelta(days=7), START - timedelta(days=1)
SVC, RET, SER = SaleItem.Kind.SERVICE, SaleItem.Kind.PRODUCT, SaleItem.Kind.SERIES


class _Base(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        # Prior day0 total 60 vs current day0 total 150 (offset-aligned).
        self._sale(date(2026, 10, 26), [(SVC, "50.00"), (RET, "10.00")])
        self._sale(START, [(SVC, "100.00"), (RET, "20.00"), (SER, "30.00")])
        # Current day2 only: prior-zero figures on that offset.
        self._sale(date(2026, 11, 4), [(SVC, "40.00")])

    def _sale(self, day, items, salon=None):
        sale = Sale.objects.create(salon=salon or self.salon,
                                   status=Sale.Status.COMPLETED)
        stamp = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(created_at=stamp, completed_at=stamp)
        for kind, price in items:
            SaleItem.objects.create(sale=sale, kind=kind, quantity=1,
                                    unit_price=Decimal(price))
        return sale


class PriorTrendTests(_Base):
    def test_both_windows_verbatim_and_bounds(self):
        r = prior_trend(self.salon, START, END)
        self.assertEqual(list(r.current),
                         list(daily_revenue_trend(self.salon, days=7, end_date=END)))
        self.assertEqual(list(r.prior), list(daily_revenue_trend(
            self.salon, days=7, end_date=PRIOR_END)))
        self.assertEqual((r.start_date, r.end_date, r.days), (START, END, 7))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR_START, PRIOR_END))
        self.assertEqual(r.previous, r.prior)
        self.assertEqual([row.offset for row in r.per_day], list(range(7)))
        self.assertEqual(set(r.by_offset), set(range(7)))
        self.assertEqual(r.by_day, r.per_day)

    def test_offset_alignment_deltas_and_percent(self):
        r = prior_trend(self.salon, START, END)
        day0, day2 = r.by_offset[0], r.by_offset[2]
        self.assertEqual((day0.current_date, day0.prior_date),
                         (START, date(2026, 10, 26)))
        self.assertEqual((day2.current_date, day2.prior_date),
                         (date(2026, 11, 4), date(2026, 10, 28)))
        for comp, want in (
            (day0.service, ("100.00", "50.00", "50.00", "100.00")),
            (day0.retail, ("20.00", "10.00", "10.00", "100.00")),
            (day0.total, ("150.00", "60.00", "90.00", "150.00")),
            (day2.service, ("40.00", "0.00", "40.00", None)),
            (day2.total, ("40.00", "0.00", "40.00", None)),
        ):
            self.assertEqual(
                (comp.current, comp.prior, comp.delta, comp.percent_change),
                tuple(Decimal(str(v)) if v is not None else None for v in want))
        self.assertEqual(set(day0.deltas),
                         {"service", "retail", "series", "total", "moving_average_7d"})

    def test_moving_average_pair_and_zero_filled_day(self):
        r = prior_trend(self.salon, START, END)
        ma0 = r.by_offset[0].moving_average_7d
        self.assertEqual((ma0.current, ma0.prior, ma0.delta, ma0.percent_change),
                         (Decimal("150.00"), Decimal("60.00"),
                          Decimal("90.00"), Decimal("150.00")))
        ma2 = r.by_offset[2].moving_average_7d
        self.assertEqual((ma2.current, ma2.prior, ma2.delta, ma2.percent_change),
                         (Decimal("63.33"), Decimal("20.00"),
                          Decimal("43.33"), Decimal("216.65")))
        day1 = r.by_offset[1]  # no sales either window: zero-filled
        self.assertEqual((day1.total.current, day1.total.prior, day1.total.delta),
                         (Decimal("0.00"), Decimal("0.00"), Decimal("0.00")))
        self.assertIsNone(day1.total.percent_change)
        self.assertIsNone(r.by_offset[0].series.percent_change)  # prior series 0

    def test_salon_isolation_and_reversed_window(self):
        self._sale(START, [(SVC, "999.00")], salon=self.other)
        day0 = prior_trend(self.salon, START, END).by_offset[0]
        self.assertEqual(day0.total.current, Decimal("150.00"))
        with self.assertRaises(ValueError): prior_trend(self.salon, END, START)
        with self.assertRaises(ValueError):
            export_prior_trend_csv(self.salon, END, START)


class PriorTrendExportTests(_Base):
    def test_dict_shape_values_and_csv_agreement(self):
        records = export_prior_trend(self.salon, START, END)
        self.assertEqual(len(records), 7)
        for record in records: self.assertEqual(list(record), PRIOR_TREND_FIELDNAMES)
        self.assertEqual([r["offset"] for r in records], list(range(7)))
        day0 = records[0]
        self.assertEqual((day0["current_service"], day0["prior_service"],
                          day0["service_delta"], day0["service_percent_change"]),
                         ("100.00", "50.00", "50.00", "100.00"))
        self.assertEqual((day0["current_date"], day0["prior_date"]),
                         (START.isoformat(), "2026-10-26"))
        self.assertEqual(day0["prior_start_date"], PRIOR_START.isoformat())
        self.assertEqual(day0["current_moving_average_7d"], "150.00")
        self.assertEqual(records[2]["service_percent_change"], "")
        rows = list(csv.DictReader(io.StringIO(
            export_prior_trend_csv(self.salon, START, END))))
        self.assertEqual(rows, [{k: str(v) for k, v in r.items()} for r in records])


class ExportPriorTrendCommandTests(_Base):
    def test_stdout_string_args_and_file_match_service(self):
        want = export_prior_trend_csv(self.salon, START, END)
        out = io.StringIO()
        call_command("export_prior_trend", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command("export_prior_trend", "--salon-id", str(self.salon.pk),
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_trend.csv")
            call_command("export_prior_trend", salon_id=self.salon.pk,
                         start_date=START, end_date=END, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh: written = fh.read()
        self.assertEqual(written, want)
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_bad_dates_and_reversed_raise(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_trend", salon_id=self.salon.pk + 999,
                         start_date=START, end_date=END, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_trend", salon_id=self.salon.pk,
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_trend", "--salon-id", str(self.salon.pk),
                         "--start-date", "2026-13-40",
                         "--end-date", END.isoformat(), stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_trend", salon_id=self.salon.pk,
                         start_date=END, end_date=START, stdout=io.StringIO())
