import csv
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.margin import ProductMarginReport, ProductMarginRow, product_margin
from catalog.margin_export import (
    MARGIN_FIELDNAMES,
    export_product_margin,
    export_product_margin_csv,
)
from catalog.models import Product, StockMovement
from checkout.models import Sale, SaleItem
from saloncore.models import Salon


class MarginFixtures(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def make_product(self, name, price="10.00", cost="6.00", salon=None, **kw):
        return Product.objects.create(
            salon=salon or self.salon, name=name, price=Decimal(price),
            cost_price=Decimal(cost) if cost is not None else None, **kw,
        )

    def sell(self, product, quantity, unit_price,
             status=Sale.Status.COMPLETED, salon=None):
        sale = Sale.objects.create(salon=salon or self.salon, status=status)
        return SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT, product=product,
            description=product.name if product else "",
            quantity=quantity, unit_price=Decimal(unit_price),
        )

    def row_for(self, report, product):
        return next(r for r in report.rows if r.product == product)


class ProductMarginTests(MarginFixtures):
    def test_margin_math_uses_current_cost_and_snapshot_revenue(self):
        product = self.make_product("Shampoo", sku="SH-001",
                                    barcode="012345678905", cost="6.00")
        self.sell(product, 2, "10.00")
        self.sell(product, 3, "12.00")  # snapshot prices: revenue 56.00
        report = product_margin(self.salon)
        self.assertIsInstance(report, ProductMarginReport)
        row = self.row_for(report, product)
        self.assertIsInstance(row, ProductMarginRow)
        self.assertEqual(row.sku, "SH-001")
        self.assertEqual(row.units_sold, 5)
        self.assertEqual(row.retail_revenue, Decimal("56.00"))
        self.assertEqual(row.unit_cost, Decimal("6.00"))
        self.assertEqual(row.cost, Decimal("30.00"))
        self.assertEqual(row.margin, Decimal("26.00"))
        self.assertEqual(row.margin_percent, Decimal("46.43"))
        self.assertEqual(report.total_units_sold, 5)
        self.assertEqual(report.total_retail_revenue, Decimal("56.00"))
        self.assertEqual(report.total_cost, Decimal("30.00"))
        self.assertEqual(report.total_margin, Decimal("26.00"))
        self.assertEqual(report.salon_id, self.salon.pk)

    def test_zero_revenue_product_has_none_percent(self):
        unsold = self.make_product("Unsold", cost="6.00")
        free = self.make_product("Freebie", cost="6.00")
        self.sell(free, 2, "0.00")  # units sold, no revenue taken
        report = product_margin(self.salon)
        row = self.row_for(report, unsold)
        self.assertEqual(row.units_sold, 0)
        self.assertEqual(row.retail_revenue, Decimal("0.00"))
        self.assertEqual(row.cost, Decimal("0.00"))
        self.assertEqual(row.margin, Decimal("0.00"))
        self.assertIsNone(row.margin_percent)
        row = self.row_for(report, free)
        self.assertEqual(row.cost, Decimal("12.00"))
        self.assertEqual(row.margin, Decimal("-12.00"))
        self.assertIsNone(row.margin_percent)

    def test_missing_cost_price_is_unknown_never_zero(self):
        product = self.make_product("No Cost", cost=None)
        self.sell(product, 2, "10.00")
        report = product_margin(self.salon)
        row = self.row_for(report, product)
        self.assertIsNone(row.unit_cost)
        self.assertIsNone(row.cost)
        self.assertIsNone(row.margin)
        self.assertIsNone(row.margin_percent)
        # Unknown cost contributes nothing to the cost/margin totals.
        self.assertEqual(report.total_cost, Decimal("0.00"))
        self.assertEqual(report.total_margin, Decimal("0.00"))
        self.assertEqual(report.total_retail_revenue, Decimal("20.00"))

    def test_only_the_given_salons_products_and_sales_count(self):
        foreign = self.make_product("Foreign", salon=self.other)
        self.sell(foreign, 9, "99.00", salon=self.other)
        own = self.make_product("Own")
        self.sell(own, 1, "10.00")
        self.sell(own, 50, "99.00", salon=self.other)  # foreign sale
        report = product_margin(self.salon)
        self.assertEqual([r.product for r in report.rows], [own])
        self.assertEqual(report.rows[0].units_sold, 1)
        self.assertEqual(report.rows[0].margin, Decimal("4.00"))

    def test_open_and_voided_sales_never_count(self):
        product = self.make_product("Shampoo")
        self.sell(product, 1, "10.00")
        self.sell(product, 100, "99.00", status=Sale.Status.OPEN)
        self.sell(product, 100, "99.00", status=Sale.Status.VOIDED)
        row = self.row_for(product_margin(self.salon), product)
        self.assertEqual(row.units_sold, 1)
        self.assertEqual(row.margin, Decimal("4.00"))

    def test_report_is_read_only(self):
        product = self.make_product("Shampoo")
        StockMovement.objects.create(
            product=product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=10)
        self.sell(product, 2, "10.00")
        before = (Product.objects.count(), StockMovement.objects.count(),
                  Sale.objects.count(), SaleItem.objects.count())
        product_margin(self.salon)
        export_product_margin(self.salon)
        export_product_margin_csv(self.salon)
        after = (Product.objects.count(), StockMovement.objects.count(),
                 Sale.objects.count(), SaleItem.objects.count())
        self.assertEqual(before, after)


class ProductMarginExportTests(MarginFixtures):
    def setUp(self):
        super().setUp()
        self.shampoo = self.make_product(
            "Shampoo", sku="SH-001", barcode="012345678905", cost="6.00")
        self.sell(self.shampoo, 5, "10.00")
        self.unsold = self.make_product("Unsold", cost="2.50")
        self.nocost = self.make_product("No Cost", cost=None)
        self.sell(self.nocost, 1, "10.00")
        foreign = self.make_product("Foreign", salon=self.other)
        self.sell(foreign, 9, "99.00", salon=self.other)

    def test_dict_rows_match_report_verbatim(self):
        records = export_product_margin(self.salon)
        report = product_margin(self.salon)
        self.assertEqual(len(records), len(report.rows))
        for record, row in zip(records, report.rows):
            self.assertEqual(list(record), MARGIN_FIELDNAMES)
            self.assertEqual(record["product_id"], row.product.pk)
            self.assertEqual(record["product_name"], row.product.name)
            self.assertEqual(record["units_sold"], row.units_sold)
            self.assertEqual(Decimal(record["retail_revenue"]),
                             row.retail_revenue)

    def test_csv_and_dict_agree(self):
        records = export_product_margin(self.salon)
        text = export_product_margin_csv(self.salon)
        self.assertEqual(text.splitlines()[0].split(","),
                         MARGIN_FIELDNAMES)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            rows,
            [{k: str(v) for k, v in record.items()} for record in records],
        )

    def test_known_values_and_none_rendering(self):
        records = {r["product_name"]: r
                   for r in export_product_margin(self.salon)}
        shampoo = records["Shampoo"]
        self.assertEqual(shampoo["retail_revenue"], "50.00")
        self.assertEqual(shampoo["unit_cost"], "6.00")
        self.assertEqual(shampoo["cost"], "30.00")
        self.assertEqual(shampoo["margin"], "20.00")
        self.assertEqual(shampoo["margin_percent"], "40.00")
        self.assertEqual(records["Unsold"]["margin_percent"], "")
        nocost = records["No Cost"]
        self.assertEqual(nocost["unit_cost"], "")
        self.assertEqual(nocost["cost"], "")
        self.assertEqual(nocost["margin"], "")
        self.assertNotIn("Foreign", export_product_margin_csv(self.salon))

    def test_empty_salon_exports_header_only_and_no_dicts(self):
        empty = Salon.objects.create(name="Empty Salon")
        self.assertEqual(export_product_margin(empty), [])
        text = export_product_margin_csv(empty)
        self.assertEqual(list(csv.DictReader(io.StringIO(text))), [])
        self.assertEqual(len(text.splitlines()), 1)


class ExportProductMarginCommandTests(MarginFixtures):
    def setUp(self):
        super().setUp()
        product = self.make_product("Shampoo", cost="6.00")
        self.sell(product, 2, "10.00")
        foreign = self.make_product("Foreign", salon=self.other)
        self.sell(foreign, 9, "99.00", salon=self.other)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_product_margin", salon_id=self.salon.pk,
                     stdout=out)
        text = out.getvalue()
        self.assertEqual(text, export_product_margin_csv(self.salon))
        self.assertIn("Shampoo", text)
        self.assertNotIn("Foreign", text)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "margin.csv")
            call_command("export_product_margin", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, export_product_margin_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_product_margin", salon_id=999999,
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "margin.csv")
            with self.assertRaises(CommandError):
                call_command("export_product_margin",
                             salon_id=self.salon.pk, output=path,
                             stdout=io.StringIO())
