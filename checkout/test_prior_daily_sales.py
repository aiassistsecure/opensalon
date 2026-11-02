"""Tests for prior daily sales, CSV export, and command.
Synthetic fixtures; current 2026-10-10, prior same weekday 2026-10-03."""
import csv
import datetime
import io
import os
import shutil
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale, SaleItem
from checkout.prior_daily_sales import prior_daily_sales
from checkout.prior_daily_sales_export import (
    EXPORT_FIELDNAMES, export_prior_daily_sales,
    export_prior_daily_sales_csv)
from checkout.summary import daily_sales_summary
from saloncore.models import Salon

D = datetime.date
DAY, PRIOR = D(2026, 10, 10), D(2026, 10, 3)


class PriorDailySalesTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        # Prior day: 1 sale, gross 100 (service 60 + product 40),
        # line discount 5 + sale discount 5 = 10, net 90.
        self._sale(self.salon, PRIOR, [("service", "60.00", 1, "5.00"),
                                       ("product", "20.00", 2, "0.00")],
                   sale_discount="5.00")
        # Current day: 2 sales, gross 325 (service 135, retail 40,
        # series 150 after qty), discounts 10, net 315; 1 voided excluded.
        self._sale(self.salon, DAY, [("service", "85.00", 1, "10.00"),
                                     ("product", "20.00", 2, "0.00")])
        self._sale(self.salon, DAY, [("service", "50.00", 1, "0.00"),
                                     ("series", "75.00", 2, "0.00")])
        self._sale(self.salon, DAY, [("service", "999.00", 1, "0.00")],
                   status=Sale.Status.VOIDED)
        self._sale(self.other, DAY, [("service", "999.00", 1, "0.00")])
        self._sale(self.other, PRIOR, [("service", "999.00", 1, "0.00")])

    def _at(self, day, hour=12):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, 0)),
            datetime.timezone.utc)

    def _sale(self, salon, day, items, status=Sale.Status.COMPLETED,
              sale_discount="0.00"):
        sale = Sale.objects.create(salon=salon, status=status,
                                   discount_amount=Decimal(sale_discount))
        for kind, price, qty, disc in items:
            SaleItem.objects.create(
                sale=sale, kind=kind, description=kind,
                unit_price=Decimal(price), quantity=qty,
                discount_amount=Decimal(disc))
        stamp = self._at(day)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        return sale

    def test_both_days_verbatim_and_prior_date(self):
        r = prior_daily_sales(self.salon, DAY)
        self.assertEqual((r.date, r.day, r.prior_date), (DAY, DAY, PRIOR))
        self.assertEqual(r.date.weekday(), r.prior_date.weekday())
        self.assertEqual(r.current, daily_sales_summary(self.salon, DAY))
        self.assertEqual(r.prior, daily_sales_summary(self.salon, PRIOR))
        self.assertEqual(r.salon_id, self.salon.pk)

    def test_delta_and_percent_change(self):
        r = prior_daily_sales(self.salon, DAY)
        self.assertEqual((r.sales_count.current, r.sales_count.prior,
                          r.sales_count.delta, r.sales_count.percent_change),
                         (2, 1, 1, Decimal("100.00")))
        self.assertEqual((r.gross_total.current, r.gross_total.prior,
                          r.gross_total.delta, r.gross_total.percent_change),
                         (Decimal("325.00"), Decimal("100.00"),
                          Decimal("225.00"), Decimal("225.00")))
        self.assertEqual((r.discount_total.current, r.discount_total.prior,
                          r.discount_total.delta),
                         (Decimal("10.00"), Decimal("10.00"), Decimal("0.00")))
        self.assertEqual((r.net_total.current, r.net_total.prior,
                          r.net_total.delta, r.net_total.percent_change),
                         (Decimal("315.00"), Decimal("90.00"),
                          Decimal("225.00"), Decimal("250.00")))

    def test_kind_split_figures(self):
        r = prior_daily_sales(self.salon, DAY)
        self.assertEqual((r.service_total.current, r.service_total.prior,
                          r.service_total.delta, r.service_total.percent_change),
                         (Decimal("135.00"), Decimal("60.00"),
                          Decimal("75.00"), Decimal("125.00")))
        self.assertEqual((r.retail_total.current, r.retail_total.prior,
                          r.retail_total.delta, r.retail_total.percent_change),
                         (Decimal("40.00"), Decimal("40.00"),
                          Decimal("0.00"), Decimal("0.00")))
        self.assertEqual((r.series_total.current, r.series_total.prior,
                          r.series_total.delta),
                         (Decimal("150.00"), Decimal("0.00"), Decimal("150.00")))
        self.assertIsNone(r.series_total.percent_change)
        self.assertEqual(r.by_kind["service"], r.service_total)
        self.assertEqual(r.by_kind["product"], r.retail_total)
        self.assertEqual(r["series"], r.series_total)

    def test_none_percent_when_prior_zero(self):
        empty_day = D(2026, 9, 26)  # prior 2026-09-19 also empty
        r = prior_daily_sales(self.salon, empty_day)
        self.assertEqual((r.sales_count.current, r.sales_count.prior), (0, 0))
        for fig in (r.sales_count, r.gross_total, r.net_total):
            self.assertIsNone(fig.percent_change)
        # Current-only day: prior zero -> None, delta == current.
        r2 = prior_daily_sales(self.salon, PRIOR)
        self.assertEqual(r2.prior_date, D(2026, 9, 26))
        self.assertIsNone(r2.gross_total.percent_change)
        self.assertEqual(r2.gross_total.delta, Decimal("100.00"))

    def test_salon_isolation(self):
        r = prior_daily_sales(self.other, DAY)
        self.assertEqual((r.sales_count.current, r.gross_total.current),
                         (1, Decimal("999.00")))
        self.assertEqual((r.sales_count.prior, r.gross_total.prior),
                         (1, Decimal("999.00")))

    def test_missing_and_bad_raise(self):
        for args in [(None, DAY), (self.salon, None), (self.salon, "bad")]:
            with self.assertRaises(ValueError):
                prior_daily_sales(*args)

    def test_csv_rows_match_service(self):
        rows = export_prior_daily_sales(self.salon, DAY)
        self.assertEqual([list(r) for r in rows], [EXPORT_FIELDNAMES] * len(rows))
        self.assertEqual([r["figure"] for r in rows],
                         ["sales_count", "gross_total", "discount_total",
                          "net_total", "service_total", "retail_total",
                          "series_total"])
        count, gross, _disc, net = rows[:4]
        self.assertEqual((count["current"], count["prior"], count["delta"],
                          count["percent_change"]), ("2", "1", "1", "100.00"))
        self.assertEqual((gross["current"], gross["prior"], gross["delta"],
                          gross["percent_change"]),
                         ("325.00", "100.00", "225.00", "225.00"))
        self.assertEqual((net["current"], net["prior"]), ("315.00", "90.00"))
        self.assertEqual((rows[6]["figure"], rows[6]["percent_change"]),
                         ("series_total", ""))
        self.assertEqual((count["date"], count["prior_date"]),
                         (DAY.isoformat(), PRIOR.isoformat()))
        text = export_prior_daily_sales_csv(self.salon, DAY)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual([{**r, "salon_id": int(r["salon_id"])} for r in parsed], rows)

    def test_command_stdout_and_file_match_service(self):
        out = io.StringIO()
        call_command("export_prior_daily_sales", salon_id=self.salon.pk,
                     date=DAY, stdout=out)
        expected = export_prior_daily_sales_csv(self.salon, DAY)
        self.assertEqual(out.getvalue(), expected)
        tmp = os.path.join(os.getcwd(), "tmp_prior_daily_test")
        os.makedirs(tmp, exist_ok=True)
        try:
            path = os.path.join(tmp, "prior.csv")
            call_command("export_prior_daily_sales", salon_id=self.salon.pk,
                         date=DAY.isoformat(), output=path, stdout=io.StringIO())
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), expected)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_command_errors(self):
        bad = os.path.join(os.getcwd(), "no_such_dir_prior_daily", "x.csv")
        cases = [dict(salon_id=self.salon.pk + 999, date=DAY),
                 dict(salon_id=self.salon.pk, date="not-a-date"),
                 dict(salon_id=self.salon.pk),
                 dict(salon_id=self.salon.pk, date=DAY, output=bad)]
        for kwargs in cases:
            with self.assertRaises(CommandError):
                call_command("export_prior_daily_sales",
                             stdout=io.StringIO(), **kwargs)
