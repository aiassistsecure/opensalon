import csv
import io
from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.stocktake_sheet import stocktake_sheet
from catalog.variance import stocktake_variance
from catalog.variance_export import (
    VARIANCE_FIELDNAMES,
    export_stocktake_variance,
    export_stocktake_variance_csv,
    variance_csv,
)
from saloncore.models import Salon


class StocktakeVarianceExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, price="10.00", sku="", barcode="",
                     salon=None):
        return Product.objects.create(
            salon=salon or self.salon, name=name, sku=sku,
            barcode=barcode, price=Decimal(price),
        )

    def move(self, product, delta):
        return StockMovement.objects.create(
            product=product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=delta,
        )

    def test_csv_header(self):
        shampoo = self.make_product("Shampoo")
        self.move(shampoo, 5)
        text = export_stocktake_variance_csv(self.salon, {shampoo: 5})
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], VARIANCE_FIELDNAMES)
        self.assertEqual(
            VARIANCE_FIELDNAMES,
            ["product_id", "product_name", "sku", "barcode",
             "expected_stock", "counted_stock", "difference",
             "unit_price", "retail_value_impact"],
        )

    def test_rows_match_service_output(self):
        shampoo = self.make_product(
            "Shampoo", price="10.00", sku="SH-001",
            barcode="012345678905")
        self.move(shampoo, 10)
        serum = self.make_product("Serum", price="19.99", sku="SE-002")
        self.move(serum, 3)
        counts = {shampoo: 6, serum: 5}
        sheet = stocktake_sheet(self.salon)

        report = stocktake_variance(sheet, counts)
        parsed = list(csv.DictReader(io.StringIO(
            export_stocktake_variance_csv(sheet, counts))))
        self.assertEqual(len(parsed), len(report.lines))
        for record, line in zip(parsed, report.lines):
            self.assertEqual(int(record["product_id"]), line.product.pk)
            self.assertEqual(record["product_name"], line.name)
            self.assertEqual(record["sku"], line.sku)
            self.assertEqual(record["barcode"], line.barcode)
            self.assertEqual(int(record["expected_stock"]),
                             line.expected_stock)
            self.assertEqual(int(record["counted_stock"]),
                             line.counted_stock)
            self.assertEqual(int(record["difference"]), line.difference)
            self.assertEqual(Decimal(record["unit_price"]),
                             line.unit_price)
            self.assertEqual(Decimal(record["retail_value_impact"]),
                             line.retail_value_impact)
        # Dict export agrees with the CSV export.
        dicts = export_stocktake_variance(self.salon, counts)
        self.assertEqual(
            [d["product_name"] for d in dicts],
            [r["product_name"] for r in parsed],
        )
        by_name = {d["product_name"]: d for d in dicts}
        self.assertEqual(by_name["Shampoo"]["retail_value_impact"],
                         "-40.00")
        self.assertEqual(by_name["Serum"]["retail_value_impact"],
                         "39.98")

    def test_salon_isolation(self):
        shampoo = self.make_product("Shampoo", price="10.00")
        self.move(shampoo, 8)
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", price="20.00", salon=other)
        self.move(foreign, 4)

        parsed = list(csv.DictReader(io.StringIO(
            export_stocktake_variance_csv(self.salon, {shampoo: 8}))))
        self.assertEqual([r["product_name"] for r in parsed], ["Shampoo"])
        parsed_other = list(csv.DictReader(io.StringIO(
            export_stocktake_variance_csv(other, {foreign: 2}))))
        self.assertEqual(
            [r["product_name"] for r in parsed_other], ["Foreign"])
        self.assertEqual(int(parsed_other[0]["difference"]), -2)

    def test_empty_is_header_only(self):
        self.assertEqual(
            export_stocktake_variance_csv(self.salon, {}),
            ",".join(VARIANCE_FIELDNAMES) + "\n",
        )
        self.assertEqual(export_stocktake_variance(self.salon, {}), [])
        self.make_product("Shampoo")
        self.assertEqual(
            export_stocktake_variance_csv(
                stocktake_sheet(self.salon), {}),
            ",".join(VARIANCE_FIELDNAMES) + "\n",
        )

    def test_alias_and_read_only(self):
        shampoo = self.make_product("Shampoo", price="10.00")
        self.move(shampoo, 4)
        before_products = Product.objects.count()
        before_moves = StockMovement.objects.count()
        self.assertEqual(
            variance_csv(self.salon, {shampoo: 3}),
            export_stocktake_variance_csv(self.salon, {shampoo: 3}),
        )
        self.assertEqual(Product.objects.count(), before_products)
        self.assertEqual(StockMovement.objects.count(), before_moves)
        self.assertEqual(shampoo.current_stock, 4)

    def test_invalid_counts_still_raise_service_error(self):
        shampoo = self.make_product("Shampoo")
        self.move(shampoo, 2)
        with self.assertRaises(ValueError):
            export_stocktake_variance_csv(self.salon, {shampoo: -1})
