import csv
import io
import json
from decimal import Decimal

from django.test import TestCase

from catalog.low_stock import DEFAULT_LOW_STOCK_THRESHOLD
from catalog.low_stock_export import (
    LOW_STOCK_FIELDNAMES,
    export_low_stock,
    export_low_stock_csv,
)
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class LowStockExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, sku="", barcode="", salon=None):
        return Product.objects.create(
            salon=salon or self.salon, name=name, sku=sku,
            barcode=barcode, price=Decimal("24.00"),
        )

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE):
        return StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta
        )

    def test_csv_header(self):
        text = export_low_stock_csv(self.salon)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], LOW_STOCK_FIELDNAMES)
        self.assertEqual(
            LOW_STOCK_FIELDNAMES,
            ["product_id", "product_name", "sku", "barcode",
             "current_stock", "threshold"],
        )

    def test_below_threshold_row(self):
        p = self.make_product("Shampoo", sku="SH-001",
                              barcode="012345678905")
        self.move(p, 10)
        self.move(p, -8, kind=StockMovement.Kind.SALE)
        well = self.make_product("Well Stocked")
        self.move(well, 99)
        records = export_low_stock(self.salon, threshold=5)
        self.assertEqual(records, [{
            "product_id": p.pk, "product_name": "Shampoo",
            "sku": "SH-001", "barcode": "012345678905",
            "current_stock": 2, "threshold": 5,
        }])
        self.assertEqual(json.loads(json.dumps(records)), records)
        parsed = list(csv.DictReader(
            io.StringIO(export_low_stock_csv(self.salon, threshold=5))))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["product_name"], "Shampoo")
        self.assertEqual(parsed[0]["sku"], "SH-001")
        self.assertEqual(parsed[0]["barcode"], "012345678905")
        self.assertEqual(int(parsed[0]["current_stock"]), 2)
        self.assertEqual(int(parsed[0]["threshold"]), 5)

    def test_empty_case_is_header_only(self):
        p = self.make_product("Well Stocked")
        self.move(p, DEFAULT_LOW_STOCK_THRESHOLD + 1)
        self.assertEqual(export_low_stock(self.salon), [])
        self.assertEqual(
            export_low_stock_csv(self.salon),
            ",".join(LOW_STOCK_FIELDNAMES) + "\n",
        )
        empty_salon = Salon.objects.create(name="Empty Salon")
        self.assertEqual(export_low_stock(empty_salon), [])
        self.assertEqual(
            export_low_stock_csv(empty_salon),
            ",".join(LOW_STOCK_FIELDNAMES) + "\n",
        )

    def test_default_threshold_and_read_only(self):
        p = self.make_product("Never Stocked")
        records = export_low_stock(self.salon)
        self.assertEqual(records[0]["current_stock"], 0)
        self.assertEqual(records[0]["threshold"],
                         DEFAULT_LOW_STOCK_THRESHOLD)
        export_low_stock_csv(self.salon)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(p.current_stock, 0)
