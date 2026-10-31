import csv
import io
import json
from decimal import Decimal

from django.test import TestCase

from catalog.export import (
    EXPORT_FIELDNAMES,
    export_products,
    export_products_csv,
)
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class ProductExportTests(TestCase):
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

    def test_exports_core_fields_and_ledger_derived_stock(self):
        p = self.make_product("Shampoo", price="10.50", sku="SH-001",
                              barcode="012345678905")
        self.move(p, 10)
        self.move(p, -3, kind=StockMovement.Kind.SALE)
        (record,) = export_products(self.salon)
        self.assertEqual(record, {
            "id": p.pk, "salon_id": self.salon.pk, "name": "Shampoo",
            "sku": "SH-001", "barcode": "012345678905",
            "price": "10.50", "active": True, "stock_on_hand": 7,
        })

    def test_result_is_json_serializable(self):
        p = self.make_product("Serum", price="19.99")
        self.move(p, 2)
        data = export_products(self.salon)
        self.assertEqual(json.loads(json.dumps(data)), data)

    def test_product_with_no_movements_exports_zero_stock(self):
        self.make_product("Never Stocked", price="15.00")
        (record,) = export_products(self.salon)
        self.assertEqual(record["stock_on_hand"], 0)

    def test_negative_stock_reported_unclamped(self):
        p = self.make_product("Oversold", price="10.00")
        self.move(p, -2, kind=StockMovement.Kind.SALE)
        (record,) = export_products(self.salon)
        self.assertEqual(record["stock_on_hand"], -2)

    def test_only_given_salons_products_exported(self):
        other = Salon.objects.create(name="Other Salon")
        self.make_product("Foreign", salon=other)
        self.make_product("Own")
        self.assertEqual(
            [r["name"] for r in export_products(self.salon)], ["Own"])
        self.assertEqual(
            [r["name"] for r in export_products(other)], ["Foreign"])

    def test_inactive_excluded_by_default_included_on_request(self):
        self.make_product("Active")
        inactive = self.make_product("Inactive", active=False)
        self.move(inactive, 4)
        self.assertEqual(
            [r["name"] for r in export_products(self.salon)], ["Active"])
        records = export_products(self.salon, include_inactive=True)
        self.assertEqual([r["name"] for r in records],
                         ["Active", "Inactive"])
        by_name = {r["name"]: r for r in records}
        self.assertFalse(by_name["Inactive"]["active"])
        self.assertEqual(by_name["Inactive"]["stock_on_hand"], 4)

    def test_ordering_by_name_then_id_and_empty_salon(self):
        self.assertEqual(export_products(self.salon), [])
        self.make_product("Beta")
        self.make_product("Alpha")
        self.make_product("Alpha")
        records = export_products(self.salon)
        self.assertEqual([r["name"] for r in records],
                         ["Alpha", "Alpha", "Beta"])
        ids = [r["id"] for r in records if r["name"] == "Alpha"]
        self.assertEqual(ids, sorted(ids))

    def test_export_is_read_only(self):
        p = self.make_product("Shampoo")
        self.move(p, 5)
        export_products(self.salon, include_inactive=True)
        export_products_csv(self.salon)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(p.current_stock, 5)

    def test_csv_header_rows_and_agreement_with_list_export(self):
        p = self.make_product("Conditioner, Deluxe", price="12.00",
                              sku="CD-1", barcode="111")
        self.move(p, 3)
        self.make_product("Balm", price="8.50")
        text = export_products_csv(self.salon)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        listed = export_products(self.salon)
        self.assertEqual(len(parsed), len(listed))
        for csv_row, record in zip(parsed, listed):
            self.assertEqual(csv_row["name"], record["name"])
            self.assertEqual(csv_row["sku"], record["sku"])
            self.assertEqual(csv_row["barcode"], record["barcode"])
            self.assertEqual(csv_row["price"], record["price"])
            self.assertEqual(int(csv_row["stock_on_hand"]),
                             record["stock_on_hand"])
        # Quoted comma in a name round-trips through the CSV.
        self.assertIn("Conditioner, Deluxe",
                      [r["name"] for r in parsed])

    def test_csv_empty_salon_is_header_only(self):
        text = export_products_csv(self.salon)
        self.assertEqual(
            text, ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_csv_respects_include_inactive(self):
        self.make_product("Active")
        self.make_product("Inactive", active=False)
        default = export_products_csv(self.salon)
        self.assertNotIn("Inactive", default)
        full = export_products_csv(self.salon, include_inactive=True)
        self.assertIn("Inactive", full)
