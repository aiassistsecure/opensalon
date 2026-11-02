import csv
import io
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.discounts import discounts_report
from insights.prior_discounts import prior_discounts
from insights.prior_discounts_export import (
    PRIOR_DISCOUNTS_FIELDNAMES,
    export_prior_discounts_csv,
)
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)
PRIOR_START = START - timedelta(days=7)
PRIOR_END = START - timedelta(days=1)


class PriorDiscountsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        # Prior window: gross 100, discounts 20, share 20%.
        self._sale(date(2026, 10, 28), "100.00",
                   sale_discount="5.00", item_discount="15.00")
        # Current window: gross 200, discounts 30, share 15%.
        self._sale(date(2026, 11, 5), "200.00",
                   sale_discount="10.00", item_discount="20.00")

    def _sale(self, day, price, sale_discount="0.00",
              item_discount="0.00", salon=None):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED,
            discount_amount=Decimal(sale_discount))
        stamp = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1,
            unit_price=Decimal(price),
            discount_amount=Decimal(item_discount))
        sale.refresh_from_db()
        return sale

    def test_both_windows_verbatim_vs_source(self):
        r = prior_discounts(self.salon, START, END)
        self.assertEqual(
            r.current, discounts_report(self.salon, START, END))
        self.assertEqual(
            r.prior,
            discounts_report(self.salon, PRIOR_START, PRIOR_END))
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (PRIOR_START, PRIOR_END))
        self.assertEqual((r.start_date, r.end_date, r.days), (START, END, 7))
        self.assertEqual(r.previous, r.prior)

    def test_delta_and_percent_change(self):
        r = prior_discounts(self.salon, START, END)
        self.assertEqual(
            (r.discount_total.current, r.discount_total.prior,
             r.discount_total.delta, r.discount_total.percent_change),
            (Decimal("30.00"), Decimal("20.00"), Decimal("10.00"),
             Decimal("50.00")))
        self.assertEqual(
            (r.gross.current, r.gross.prior, r.gross.delta,
             r.gross.percent_change),
            (Decimal("200.00"), Decimal("100.00"), Decimal("100.00"),
             Decimal("100.00")))
        self.assertEqual(
            (r.discount_share_percent.current,
             r.discount_share_percent.prior,
             r.discount_share_percent.delta,
             r.discount_share_percent.percent_change),
            (Decimal("15.00"), Decimal("20.00"), Decimal("-5.00"),
             Decimal("-25.00")))
        self.assertEqual(set(r.deltas), {
            "discount_total", "gross", "discount_share_percent"})

    def test_percent_change_none_when_prior_zero(self):
        other = Salon.objects.create(name="Fresh", timezone="UTC")
        self._sale(date(2026, 11, 5), "50.00",
                   item_discount="5.00", salon=other)
        r = prior_discounts(other, START, END)
        self.assertEqual(r.prior.gross, Decimal("0.00"))
        for comp in (r.discount_total, r.gross):
            self.assertIsNone(comp.percent_change)
            self.assertEqual(comp.delta, comp.current)
        # Prior share is undefined (zero gross), so no share delta.
        self.assertIsNone(r.prior.discount_share_percent)
        self.assertIsNone(r.discount_share_percent)

    def test_reversed_window_raises(self):
        with self.assertRaises(ValueError):
            prior_discounts(self.salon, END, START)
        with self.assertRaises(ValueError):
            export_prior_discounts_csv(self.salon, END, START)


class PriorDiscountsExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")

    def test_csv_shape_and_values_match_service(self):
        text = export_prior_discounts_csv(self.salon, START, END)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], PRIOR_DISCOUNTS_FIELDNAMES)
        self.assertEqual([row[0] for row in rows[1:]],
                         ["discount_total", "gross",
                          "discount_share_percent"])
        result = prior_discounts(self.salon, START, END)
        by_metric = {row["metric"]: row
                     for row in csv.DictReader(io.StringIO(text))}
        for name in ("discount_total", "gross"):
            comp = getattr(result, name)
            self.assertEqual(Decimal(by_metric[name]["current"]),
                             comp.current)
            self.assertEqual(Decimal(by_metric[name]["prior"]), comp.prior)
            self.assertEqual(Decimal(by_metric[name]["delta"]), comp.delta)
        # Empty salon: shares are None and render empty throughout.
        share_row = by_metric["discount_share_percent"]
        self.assertEqual(share_row["current"], "")
        self.assertEqual(share_row["prior"], "")
        self.assertEqual(share_row["delta"], "")
        self.assertEqual(share_row["percent_change"], "")
        self.assertEqual(by_metric["gross"]["current_start_date"],
                         START.isoformat())
        self.assertEqual(by_metric["gross"]["prior_start_date"],
                         PRIOR_START.isoformat())
        self.assertEqual(by_metric["gross"]["prior_end_date"],
                         PRIOR_END.isoformat())


class ExportPriorDiscountsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Example Salon", timezone="UTC")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_discounts", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_discounts_csv(self.salon, START, END))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command("export_prior_discounts",
                     "--salon-id", str(self.salon.pk),
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_discounts_csv(self.salon, START, END))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_discounts.csv")
            call_command("export_prior_discounts",
                         salon_id=self.salon.pk, start_date=START,
                         end_date=END, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written,
            export_prior_discounts_csv(self.salon, START, END))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_discounts",
                         salon_id=self.salon.pk + 999,
                         start_date=START, end_date=END,
                         stdout=io.StringIO())

    def test_missing_and_invalid_dates_raise_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_discounts",
                         salon_id=self.salon.pk, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_discounts",
                         salon_id=self.salon.pk, start_date="not-a-date",
                         end_date=END, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_discounts", "--salon-id",
                         str(self.salon.pk), "--start-date", "2026-13-40",
                         "--end-date", END.isoformat(), stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_discounts",
                         salon_id=self.salon.pk, start_date=END,
                         end_date=START, stdout=io.StringIO())
