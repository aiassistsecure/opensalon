"""Tests for prior-period product sales / margin: service, export, commands."""
import csv
import io
import os
import tempfile
from datetime import date, datetime, time, timedelta, timezone as dt_tz
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from catalog.margin import product_margin
from catalog.models import Product
from catalog.prior_product_sales import (
    prior_product_margin, prior_product_sales)
from catalog.prior_product_sales_export import (
    PRIOR_PRODUCT_MARGIN_FIELDNAMES, PRIOR_PRODUCT_SALES_FIELDNAMES,
    export_prior_product_margin, export_prior_product_margin_csv,
    export_prior_product_sales, export_prior_product_sales_csv)
from catalog.product_sales import product_sales
from checkout.models import Sale, SaleItem
from saloncore.models import Salon

DAY = date(2026, 10, 3)
PRIOR = DAY - timedelta(days=1)


def at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=dt_tz.utc)


class PriorProductSalesTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.alpha = self.make_product("Alpha", sku="A-1", barcode="111",
                                       cost="6.00")
        self.beta = self.make_product("Beta", sku="B-1", barcode="222",
                                      cost=None)
        self.gamma = self.make_product("Gamma", sku="G-1", barcode="333",
                                       cost="4.00")
        self.sell(self.alpha, 2, "10.00", on=PRIOR)
        self.sell(self.gamma, 4, "10.00", on=PRIOR)
        self.sell(self.alpha, 3, "10.00", on=DAY)
        self.sell(self.beta, 1, "5.00", on=DAY)

    def make_product(self, name, sku="", barcode="", cost="6.00"):
        return Product.objects.create(
            salon=self.salon, name=name, sku=sku, barcode=barcode,
            price=Decimal("10.00"),
            cost_price=Decimal(cost) if cost is not None else None)

    def sell(self, product, qty, price, on):
        sale = Sale.objects.create(salon=self.salon,
                                   status=Sale.Status.COMPLETED)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT, product=product,
            description=product.name, quantity=qty,
            unit_price=Decimal(price))
        Sale.objects.filter(pk=sale.pk).update(completed_at=at(on),
                                               created_at=at(on))

    def test_sales_both_windows_verbatim_and_totals(self):
        r = prior_product_sales(self.salon, DAY, DAY)
        self.assertEqual((r.start_date, r.end_date, r.prior_start_date,
                          r.prior_end_date), (DAY, DAY, PRIOR, PRIOR))
        self.assertEqual((r.days, r.salon_id), (1, self.salon.pk))
        self.assertEqual(r.current, product_sales(self.salon, DAY, DAY))
        self.assertEqual(r.prior, product_sales(self.salon, PRIOR, PRIOR))
        self.assertEqual((r.total_units_sold.current,
                          r.total_units_sold.prior,
                          r.total_units_sold.delta,
                          r.total_units_sold.percent_change),
                         (4, 6, -2, Decimal("-33.33")))
        self.assertEqual((r.total_retail_revenue.current,
                          r.total_retail_revenue.prior,
                          r.total_retail_revenue.delta,
                          r.total_retail_revenue.percent_change),
                         (Decimal("35.00"), Decimal("60.00"),
                          Decimal("-25.00"), Decimal("-41.67")))

    def test_sales_per_product_deltas(self):
        r = prior_product_sales(self.salon, start_date="2026-10-03",
                                end_date="2026-10-03")
        a = r.for_product(self.alpha)
        self.assertEqual((a.sku, a.barcode), ("A-1", "111"))
        self.assertEqual((a.units_sold.current, a.units_sold.prior,
                          a.units_sold.delta,
                          a.units_sold.percent_change),
                         (3, 2, 1, Decimal("50.00")))
        self.assertEqual(a.retail_revenue.delta, Decimal("10.00"))
        b = r.for_product(self.beta.pk)  # current only: prior zero
        self.assertEqual((b.units_sold.current, b.units_sold.prior),
                         (1, 0))
        self.assertIsNone(b.units_sold.percent_change)
        g = r.for_product(self.gamma)  # prior only: current zero
        self.assertEqual((g.retail_revenue.current, g.retail_revenue.prior,
                          g.retail_revenue.percent_change),
                         (Decimal("0.00"), Decimal("40.00"),
                          Decimal("-100.00")))
        payload = r.as_dict()
        self.assertEqual(payload["prior_start_date"], PRIOR.isoformat())
        self.assertEqual(payload["by_product"][0]["product_id"],
                         r.by_product[0].product_id)

    def test_equal_length_multi_day_and_errors(self):
        start = DAY - timedelta(days=1)
        r = prior_product_sales(self.salon, start, DAY)
        self.assertEqual((r.days, r.prior_start_date, r.prior_end_date),
                         (2, start - timedelta(days=2),
                          start - timedelta(days=1)))
        self.assertEqual(r.total_units_sold.current, 10)
        for call in (lambda: prior_product_sales(self.salon),
                     lambda: prior_product_sales(self.salon, start=DAY),
                     lambda: prior_product_sales(
                         self.salon, DAY + timedelta(days=1), DAY),
                     lambda: prior_product_margin(self.salon, end=DAY),
                     lambda: export_prior_product_sales_csv(self.salon, DAY)):
            with self.assertRaises(ValueError):
                call()

    def test_margin_both_windows_verbatim_and_deltas(self):
        r = prior_product_margin(self.salon, DAY, DAY)
        self.assertEqual(r.current, product_margin(self.salon, DAY, DAY))
        self.assertEqual(r.prior, product_margin(self.salon, PRIOR, PRIOR))
        self.assertEqual((r.total_cost.current, r.total_cost.prior,
                          r.total_cost.delta),
                         (Decimal("18.00"), Decimal("28.00"),
                          Decimal("-10.00")))
        self.assertEqual((r.total_margin.current, r.total_margin.prior,
                          r.total_margin.delta,
                          r.total_margin.percent_change),
                         (Decimal("12.00"), Decimal("32.00"),
                          Decimal("-20.00"), Decimal("-62.50")))
        a = r.for_product(self.alpha)
        self.assertEqual((a.unit_cost, a.cost.current, a.cost.prior),
                         (Decimal("6.00"), Decimal("18.00"),
                          Decimal("12.00")))
        self.assertEqual((a.margin.current, a.margin.prior,
                          a.margin.delta, a.margin.percent_change),
                         (Decimal("12.00"), Decimal("8.00"),
                          Decimal("4.00"), Decimal("50.00")))
        self.assertEqual((a.margin_percent.current,
                          a.margin_percent.prior,
                          a.margin_percent.delta,
                          a.margin_percent.percent_change),
                         (Decimal("40.00"), Decimal("40.00"),
                          Decimal("0.00"), Decimal("0.00")))
        b = r.for_product(self.beta)  # no cost: unknown, never zero
        self.assertIsNone(b.unit_cost)
        self.assertIsNone(b.cost.current)
        self.assertIsNone(b.cost.delta)
        self.assertIsNone(b.margin.percent_change)
        g = r.for_product(self.gamma)  # zero current revenue: pct None
        self.assertIsNone(g.margin_percent.current)
        self.assertEqual(g.margin_percent.prior, Decimal("60.00"))
        self.assertIsNone(g.margin_percent.delta)

    def test_empty_window_is_zeroed(self):
        empty = DAY + timedelta(days=30)
        r = prior_product_sales(self.salon, empty, empty)
        self.assertEqual(len(r.by_product), 3)
        self.assertEqual(r.total_units_sold.current, 0)
        self.assertIsNone(r.total_units_sold.percent_change)
        rows = export_prior_product_sales(self.salon, empty, empty)
        self.assertEqual(len(rows), 4)  # total + every product

    def test_sales_export_dicts_and_csv_agree(self):
        rows = export_prior_product_sales(self.salon, DAY, DAY)
        self.assertEqual(list(rows[0].keys()),
                         PRIOR_PRODUCT_SALES_FIELDNAMES)
        self.assertEqual(len(rows), 4)
        total, alpha = rows[0], next(
            r for r in rows if r["product_name"] == "Alpha")
        self.assertEqual((total["product_id"], total["current_units_sold"],
                          total["units_sold_percent_change"]),
                         ("", 4, Decimal("-33.33")))
        self.assertEqual((alpha["current_retail_revenue"],
                          alpha["prior_retail_revenue"],
                          alpha["retail_revenue_delta"]),
                         (Decimal("30.00"), Decimal("20.00"),
                          Decimal("10.00")))
        text = export_prior_product_sales_csv(self.salon, DAY, DAY)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(parsed[0].keys()),
                         PRIOR_PRODUCT_SALES_FIELDNAMES)
        self.assertEqual((parsed[0]["current_units_sold"],
                          parsed[0]["units_sold_percent_change"],
                          parsed[0]["prior_end_date"]),
                         ("4", "-33.33", PRIOR.isoformat()))
        beta = next(r for r in parsed if r["product_name"] == "Beta")
        self.assertEqual(beta["retail_revenue_percent_change"], "")

    def test_margin_export_dicts_and_csv_agree(self):
        rows = export_prior_product_margin(self.salon, DAY, DAY)
        self.assertEqual(list(rows[0].keys()),
                         PRIOR_PRODUCT_MARGIN_FIELDNAMES)
        self.assertEqual(len(rows), 4)
        self.assertIsNone(rows[0]["current_margin_percent"])
        alpha = next(r for r in rows if r["product_name"] == "Alpha")
        self.assertEqual((alpha["unit_cost"], alpha["current_margin"],
                          alpha["margin_percent_percent_change"]),
                         (Decimal("6.00"), Decimal("12.00"),
                          Decimal("0.00")))
        beta = next(r for r in rows if r["product_name"] == "Beta")
        self.assertIsNone(beta["current_cost"])
        text = export_prior_product_margin_csv(self.salon, DAY, DAY)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(parsed[0].keys()),
                         PRIOR_PRODUCT_MARGIN_FIELDNAMES)
        prow = next(r for r in parsed if r["product_name"] == "Alpha")
        self.assertEqual((prow["unit_cost"], prow["current_margin"],
                          prow["prior_margin"]), ("6.00", "12.00", "8.00"))
        brow = next(r for r in parsed if r["product_name"] == "Beta")
        self.assertEqual(brow["current_cost"], "")

    def test_commands_stdout_file_and_errors(self):
        for name, service in (
                ("export_prior_product_sales",
                 export_prior_product_sales_csv),
                ("export_prior_product_margin",
                 export_prior_product_margin_csv)):
            expected = service(self.salon, DAY, DAY)
            out = io.StringIO()
            call_command(name, salon_id=self.salon.pk, start_date=DAY,
                         end_date=DAY, stdout=out)
            self.assertEqual(out.getvalue(), expected)
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "out.csv")
                call_command(name, salon_id=self.salon.pk,
                             start_date="2026-10-03",
                             end_date="2026-10-03", output=path)
                with open(path, encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), expected)
            for kwargs in (dict(salon_id=self.salon.pk + 1000,
                                start_date=DAY, end_date=DAY),
                           dict(salon_id=self.salon.pk,
                                start_date=DAY + timedelta(days=1),
                                end_date=DAY),
                           dict(salon_id=self.salon.pk, start_date="bad",
                                end_date=DAY),
                           dict(salon_id=self.salon.pk)):
                with self.assertRaises(CommandError):
                    call_command(name, stdout=io.StringIO(), **kwargs)
