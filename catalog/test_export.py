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
                     salon=None, active=True, **extra):
        return Product.objects.create(
            salon=salon or self.salon, name=name, sku=sku,
            barcode=barcode, price=Decimal(price), active=active,
            **extra,
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
            "brand_name": "", "category_name": "", "product_type": "",
            "cost_price": None, "external_id": "", "payload": {},
        })
        self.assertEqual(list(record.keys()), EXPORT_FIELDNAMES)

    def test_exports_stored_verbatim_fields(self):
        payload = {"source": "phorest", "nested": {"size": "250ml"}}
        p = self.make_product(
            "Shampoo", brand_name="Aveda", category_name="Hair Care",
            product_type="retail", external_id="ext-42",
            cost_price=Decimal("6.25"), payload=payload)
        self.move(p, 1)
        (record,) = export_products(self.salon)
        self.assertEqual(record["brand_name"], "Aveda")
        self.assertEqual(record["category_name"], "Hair Care")
        self.assertEqual(record["product_type"], "retail")
        self.assertEqual(record["cost_price"], "6.25")
        self.assertEqual(record["external_id"], "ext-42")
        self.assertEqual(record["payload"], payload)
        self.assertEqual(json.loads(json.dumps(record)), record)

    def test_verbatim_fields_on_inactive_products(self):
        inactive = self.make_product(
            "Retired", active=False, brand_name="BrandX",
            category_name="Old", product_type="backbar",
            external_id="ext-9", cost_price=Decimal("3.00"),
            payload={"legacy": True})
        self.move(inactive, 2)
        (record,) = export_products(self.salon, include_inactive=True)
        self.assertEqual(record["brand_name"], "BrandX")
        self.assertEqual(record["cost_price"], "3.00")
        self.assertEqual(record["external_id"], "ext-9")
        self.assertEqual(record["payload"], {"legacy": True})

    def test_csv_verbatim_fields_and_payload_json_cell(self):
        payload = {"b": 2, "a": 1}
        self.make_product(
            "Shampoo", brand_name="Aveda", category_name="Hair Care",
            product_type="retail", external_id="ext-42",
            cost_price=Decimal("6.25"), payload=payload)
        self.make_product("No Cost")
        text = export_products_csv(self.salon)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(rows[0].keys()), EXPORT_FIELDNAMES)
        by_name = {r["name"]: r for r in rows}
        row = by_name["Shampoo"]
        self.assertEqual(row["brand_name"], "Aveda")
        self.assertEqual(row["category_name"], "Hair Care")
        self.assertEqual(row["product_type"], "retail")
        self.assertEqual(row["cost_price"], "6.25")
        self.assertEqual(row["external_id"], "ext-42")
        self.assertEqual(json.loads(row["payload"]), payload)
        # No cost recorded exports an empty cell, never zero.
        self.assertEqual(by_name["No Cost"]["cost_price"], "")
        self.assertEqual(json.loads(by_name["No Cost"]["payload"]), {})

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


class ProductExportProductTypeTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, salon=None, active=True, **extra):
        return Product.objects.create(
            salon=salon or self.salon, name=name,
            price=Decimal("10.00"), active=active, **extra)

    def test_default_none_is_unfiltered(self):
        self.make_product("A", product_type="retail")
        self.make_product("B", product_type="backbar")
        self.make_product("C")
        self.assertEqual(export_products(self.salon),
                         export_products(self.salon, product_type=None))
        self.assertEqual(export_products_csv(self.salon),
                         export_products_csv(self.salon, product_type=None))
        self.assertEqual([r["name"] for r in export_products(self.salon)],
                         ["A", "B", "C"])

    def test_exact_stored_product_type_only(self):
        self.make_product("Retail", product_type="retail")
        self.make_product("Capital", product_type="Retail")
        self.make_product("Longer", product_type="retail-pro")
        self.make_product("CategoryTrap", product_type="backbar",
                          category_name="retail")
        self.assertEqual(
            [r["name"] for r in export_products(
                self.salon, product_type="retail")], ["Retail"])

    def test_empty_string_matches_only_blank_type(self):
        self.make_product("Blank")
        self.make_product("Typed", product_type="retail")
        self.assertEqual(
            [r["name"] for r in export_products(
                self.salon, product_type="")], ["Blank"])

    def test_no_match_exports_empty(self):
        self.make_product("A", product_type="retail")
        self.assertEqual(export_products(self.salon, product_type="nope"), [])
        self.assertEqual(
            export_products_csv(self.salon, product_type="nope"),
            ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_composes_with_include_inactive(self):
        self.make_product("ActiveRetail", product_type="retail")
        self.make_product("ActiveBackbar", product_type="backbar")
        self.make_product("InactiveRetail", active=False,
                          product_type="retail")
        self.make_product("InactiveBackbar", active=False,
                          product_type="backbar")
        self.assertEqual(
            [r["name"] for r in export_products(
                self.salon, product_type="retail")], ["ActiveRetail"])
        self.assertEqual(
            [r["name"] for r in export_products(
                self.salon, include_inactive=True, product_type="retail")],
            ["ActiveRetail", "InactiveRetail"])

    def test_csv_respects_product_type_and_agrees(self):
        self.make_product("Retail", product_type="retail")
        self.make_product("Backbar", product_type="backbar")
        text = export_products_csv(self.salon, product_type="retail")
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual([r["name"] for r in rows], ["Retail"])
        listed = export_products(self.salon, product_type="retail")
        self.assertEqual([r["name"] for r in rows],
                         [r["name"] for r in listed])
