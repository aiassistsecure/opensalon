import csv
import io
import json
from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.stocktake_sheet import stocktake_sheet
from catalog.stocktake_sheet_export import (
    STOCKTAKE_SHEET_FIELDNAMES,
    export_stocktake_sheet,
    export_stocktake_sheet_csv,
)
from saloncore.models import Salon


class StocktakeSheetExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, sku="", barcode="", price="24.00",
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
        text = export_stocktake_sheet_csv(self.salon)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], STOCKTAKE_SHEET_FIELDNAMES)
        self.assertEqual(
            STOCKTAKE_SHEET_FIELDNAMES,
            ["product_id", "product_name", "sku", "barcode",
             "on_hand", "retail_price"],
        )

    def test_row_matches_service_verbatim(self):
        p = self.make_product("Shampoo", sku="SH-001",
                              barcode="012345678905", price="18.50")
        self.move(p, 10)
        self.move(p, -7, kind=StockMovement.Kind.SALE)
        self.move(p, -1, kind=StockMovement.Kind.ADJUSTMENT)
        records = export_stocktake_sheet(self.salon)
        self.assertEqual(records, [{
            "product_id": p.pk, "product_name": "Shampoo",
            "sku": "SH-001", "barcode": "012345678905",
            "on_hand": 2, "retail_price": "18.50",
        }])
        # Agrees field-for-field with the service's own rows.
        sheet = stocktake_sheet(self.salon)
        self.assertEqual(len(records), len(sheet))
        self.assertEqual(records[0]["on_hand"], sheet[0].on_hand)
        self.assertEqual(
            records[0]["retail_price"], str(sheet[0].retail_price))
        self.assertEqual(json.loads(json.dumps(records)), records)
        parsed = list(csv.DictReader(
            io.StringIO(export_stocktake_sheet_csv(self.salon))))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["product_name"], "Shampoo")
        self.assertEqual(int(parsed[0]["on_hand"]), 2)
        self.assertEqual(parsed[0]["retail_price"], "18.50")

    def test_ordering_no_movements_and_salon_scope(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        self.move(foreign, 9)
        self.make_product("Conditioner")
        balm = self.make_product("Balm", price="9.00")
        self.move(balm, 1)
        records = export_stocktake_sheet(self.salon)
        self.assertEqual(
            [r["product_name"] for r in records],
            ["Balm", "Conditioner"])
        self.assertEqual([r["on_hand"] for r in records], [1, 0])
        self.assertEqual(
            [r["product_name"] for r in export_stocktake_sheet(other)],
            ["Foreign"])

    def test_inactive_excluded_and_empty_is_header_only(self):
        retired = self.make_product("Retired", active=False)
        self.move(retired, 12)
        self.assertEqual(export_stocktake_sheet(self.salon), [])
        self.assertEqual(
            export_stocktake_sheet_csv(self.salon),
            ",".join(STOCKTAKE_SHEET_FIELDNAMES) + "\n",
        )
        empty = Salon.objects.create(name="Empty Salon")
        self.assertEqual(export_stocktake_sheet(empty), [])
        self.assertEqual(
            export_stocktake_sheet_csv(empty),
            ",".join(STOCKTAKE_SHEET_FIELDNAMES) + "\n",
        )

    def test_read_only(self):
        p = self.make_product("Shampoo")
        self.move(p, 3)
        export_stocktake_sheet(self.salon)
        export_stocktake_sheet_csv(self.salon)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(p.current_stock, 3)
