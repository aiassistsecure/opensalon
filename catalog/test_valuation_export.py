import csv
import io
from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.valuation import stock_valuation
from catalog.valuation_export import (
    VALUATION_FIELDNAMES,
    export_stock_valuation_csv,
    valuation_csv,
)
from saloncore.models import Salon


class StockValuationExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, price="24.00", sku="", barcode="",
                     salon=None, active=True):
        return Product.objects.create(
            salon=salon or self.salon, name=name, sku=sku,
            barcode=barcode, price=Decimal(price), active=active,
        )

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE):
        return StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta
        )

    def test_csv_header(self):
        text = export_stock_valuation_csv(self.salon)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], VALUATION_FIELDNAMES)
        self.assertEqual(
            VALUATION_FIELDNAMES,
            ["product_id", "product_name", "sku", "barcode",
             "on_hand", "unit_price", "retail_value"],
        )

    def test_rows_match_service_output_for_same_fixture(self):
        shampoo = self.make_product(
            "Shampoo", price="10.00", sku="SH-001",
            barcode="012345678905")
        self.move(shampoo, 10)
        self.move(shampoo, -4, kind=StockMovement.Kind.SALE)
        serum = self.make_product("Serum", price="19.99", sku="SE-002")
        self.move(serum, 3)
        inactive = self.make_product("Inactive", price="10.00",
                                     active=False)
        self.move(inactive, 100)
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        self.move(foreign, 5)

        report = stock_valuation(self.salon)
        parsed = list(csv.DictReader(
            io.StringIO(export_stock_valuation_csv(self.salon))))
        self.assertEqual(len(parsed), len(report.rows))
        for record, row in zip(parsed, report.rows):
            self.assertEqual(int(record["product_id"]), row.product.pk)
            self.assertEqual(record["product_name"], row.product.name)
            self.assertEqual(record["sku"], row.sku)
            self.assertEqual(record["barcode"], row.barcode)
            self.assertEqual(int(record["on_hand"]), row.on_hand)
            self.assertEqual(Decimal(record["unit_price"]),
                             row.unit_price)
            self.assertEqual(Decimal(record["retail_value"]),
                             row.retail_value)
        # Service order (retail value descending) is preserved.
        self.assertEqual(
            [r["product_name"] for r in parsed],
            [r.product.name for r in report.rows],
        )

    def test_empty_stock_case_is_header_only(self):
        self.assertEqual(
            export_stock_valuation_csv(self.salon),
            ",".join(VALUATION_FIELDNAMES) + "\n",
        )
        # Active product with no movements: zero row, as service.
        self.make_product("Never Stocked", price="15.00")
        parsed = list(csv.DictReader(
            io.StringIO(export_stock_valuation_csv(self.salon))))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(int(parsed[0]["on_hand"]), 0)
        self.assertEqual(Decimal(parsed[0]["retail_value"]),
                         Decimal("0.00"))

    def test_alias_matches(self):
        self.make_product("Shampoo", price="10.00")
        self.assertEqual(valuation_csv(self.salon),
                         export_stock_valuation_csv(self.salon))

    def test_read_only(self):
        p = self.make_product("Shampoo", price="10.00")
        self.move(p, 4)
        before_products = Product.objects.count()
        before_moves = StockMovement.objects.count()
        export_stock_valuation_csv(self.salon)
        self.assertEqual(Product.objects.count(), before_products)
        self.assertEqual(StockMovement.objects.count(), before_moves)
        self.assertEqual(p.current_stock, 4)
