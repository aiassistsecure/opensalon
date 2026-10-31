import csv
import io
import json
from decimal import Decimal

from django.test import TestCase

from catalog.models import Product
from catalog.search import search_products
from catalog.search_export import (
    EXPORT_FIELDNAMES,
    export_search_products,
    export_search_products_csv,
    search_export_row,
)
from saloncore.models import Salon


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class SearchExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def make_product(self, name, sku="", barcode="", salon=None,
                     active=True, price="24.00"):
        return Product.objects.create(
            salon=salon or self.salon, name=name, sku=sku,
            barcode=barcode, price=Decimal(price), active=active,
        )

    def test_header_and_row_values(self):
        p = self.make_product(
            "Lavender Shampoo", sku="SH-001", barcode="012345678905",
            price="24.5",
        )
        self.assertEqual(
            EXPORT_FIELDNAMES,
            ["id", "product_id", "salon_id", "name", "sku",
             "barcode", "price", "active"],
        )
        rows = export_search_products(self.salon, "shampoo")
        self.assertEqual(rows, [{
            "id": p.pk, "product_id": p.pk, "salon_id": self.salon.pk,
            "name": "Lavender Shampoo", "sku": "SH-001",
            "barcode": "012345678905", "price": "24.50", "active": True,
        }])
        self.assertEqual(list(rows[0]), EXPORT_FIELDNAMES)
        self.assertEqual(json.loads(json.dumps(rows)), rows)
        text = export_search_products_csv(self.salon, "shampoo")
        self.assertEqual(
            text.splitlines()[0], ",".join(EXPORT_FIELDNAMES)
        )
        csv_rows = _rows(text)
        self.assertEqual(len(csv_rows), 1)
        self.assertEqual(csv_rows[0]["name"], "Lavender Shampoo")
        self.assertEqual(csv_rows[0]["sku"], "SH-001")
        self.assertEqual(csv_rows[0]["barcode"], "012345678905")
        self.assertEqual(csv_rows[0]["price"], "24.50")
        self.assertTrue(text.endswith("\n"))

    def test_rows_match_service(self):
        self.make_product("Shampoo Deluxe", sku="SH-1")
        self.make_product("Mask Deluxe", barcode="999")
        self.make_product("Conditioner")
        for query in ("Deluxe", "SH-1", "999"):
            expected = list(search_products(self.salon, query))
            rows = export_search_products(self.salon, query)
            self.assertEqual(
                [r["product_id"] for r in rows], [p.pk for p in expected]
            )
            self.assertEqual(
                rows, [search_export_row(p) for p in expected]
            )
            csv_rows = _rows(
                export_search_products_csv(self.salon, query)
            )
            self.assertEqual(
                [r["product_id"] for r in csv_rows],
                [str(r["product_id"]) for r in rows],
            )

    def test_salon_isolation(self):
        foreign = self.make_product(
            "Lavender Shampoo", sku="GL-100", barcode="0123",
            salon=self.other,
        )
        own = self.make_product("Lavender Conditioner")
        for query in ("Lavender Shampoo", "GL-100", "0123"):
            rows = export_search_products(self.salon, query)
            self.assertNotIn(foreign.pk, [r["product_id"] for r in rows])
        self.assertEqual(
            [r["product_id"] for r in
             export_search_products(self.salon, "Lavender")],
            [own.pk],
        )
        self.assertEqual(
            [r["product_id"] for r in
             export_search_products(self.other, "GL-100")],
            [foreign.pk],
        )

    def test_no_match_and_blank_query(self):
        self.make_product("Gel", sku="GL-100", barcode="0123")
        self.assertEqual(export_search_products(self.salon, "nope"), [])
        self.assertEqual(export_search_products(self.salon, ""), [])
        self.assertEqual(export_search_products(self.salon, None), [])
        text = export_search_products_csv(self.salon, "nope")
        self.assertEqual(text, ",".join(EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(_rows(text), [])

    def test_ordering_and_inactive_passthrough(self):
        shampoo = self.make_product("Shampoo Deluxe")
        mask = self.make_product("Mask Deluxe")
        retired = self.make_product("Aardvark Deluxe", active=False)
        rows = export_search_products(self.salon, "Deluxe")
        self.assertEqual(
            [r["product_id"] for r in rows], [mask.pk, shampoo.pk]
        )
        rows = export_search_products(
            self.salon, "Deluxe", include_inactive=True
        )
        self.assertEqual(
            [r["product_id"] for r in rows],
            [retired.pk, mask.pk, shampoo.pk],
        )
        self.assertFalse(rows[0]["active"])

    def test_read_only(self):
        self.make_product("Gel", sku="GL-100")
        export_search_products(self.salon, "Gel")
        export_search_products_csv(self.salon, "Gel")
        self.assertEqual(Product.objects.count(), 1)
