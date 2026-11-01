"""import_products: type-faithful mapping, verbatim payload,
opening stock as a movement, resumable re-runs."""
import json
import tempfile
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from catalog.models import Product, StockMovement
from saloncore.models import Salon

RECORDS = [
    {
        "productId": "p-1", "name": "Aveda Shampoo", "code": "11511",
        "barcode": "018084000001", "price": 38.0, "reorderCost": 19.5,
        "brandName": "Aveda", "categoryName": "Hair Care",
        "type": "RETAIL", "archived": False, "quantityInStock": 6,
        "parentProductId": "parent-9",
    },
    {
        "productId": "p-2", "name": "Colour Tube 7N", "code": "",
        "barcode": "", "price": 12.75, "reorderCost": None,
        "brandName": "Aveda", "categoryName": "Colour",
        "type": "COLOUR", "archived": False, "quantityInStock": 0,
    },
    {"productId": "", "name": "No Id", "price": 1.0},
]


class ImportProductsTests(TestCase):
    def _run(self, records=RECORDS):
        fh = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        )
        json.dump(records, fh)
        fh.close()
        out = StringIO()
        call_command(
            "import_products", fh.name, "--salon", "Test Salon", stdout=out
        )
        return out.getvalue()

    def test_import_maps_faithfully(self):
        out = self._run()
        self.assertIn("'created': 2", out)
        self.assertIn("'skipped': 1", out)
        shampoo = Product.objects.get(external_id="p-1")
        self.assertEqual(shampoo.price, Decimal("38.00"))
        self.assertEqual(shampoo.cost_price, Decimal("19.50"))
        self.assertEqual(shampoo.barcode, "018084000001")
        self.assertEqual(shampoo.sku, "11511")
        self.assertEqual(shampoo.product_type, "RETAIL")
        self.assertEqual(shampoo.payload["parentProductId"], "parent-9")
        self.assertEqual(shampoo.current_stock, 6)
        moves = StockMovement.objects.filter(product=shampoo)
        self.assertEqual(moves.count(), 1)
        self.assertEqual(moves.first().kind, StockMovement.Kind.RECEIVE)
        colour = Product.objects.get(external_id="p-2")
        self.assertIsNone(colour.cost_price)
        self.assertEqual(colour.current_stock, 0)
        salon = Salon.objects.get(name="Test Salon")
        self.assertEqual(salon.products.count(), 2)

    def test_rerun_is_unchanged_and_never_restocks(self):
        self._run()
        out = self._run()
        self.assertIn("'unchanged': 2", out)
        self.assertIn("'created': 0", out)
        shampoo = Product.objects.get(external_id="p-1")
        self.assertEqual(shampoo.current_stock, 6)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_archived_string_false_imports_active(self):
        # TF-2 regression: string "false" is truthy — the old
        # ``not record.get("archived")`` made this product inactive.
        self._run([{
            "productId": "p-str-false", "name": "Live Product",
            "price": 10.0, "archived": "false",
        }])
        self.assertTrue(
            Product.objects.get(external_id="p-str-false").active)

    def test_archived_string_true_imports_inactive(self):
        self._run([{
            "productId": "p-str-true", "name": "Dead Product",
            "price": 10.0, "archived": "true",
        }])
        self.assertFalse(
            Product.objects.get(external_id="p-str-true").active)

    def test_archived_string_variants(self):
        cases = [
            ("False", True), ("TRUE", False), ("0", True),
            ("1", False), ("no", True), ("yes", False),
            (0, True), (1, False),
        ]
        records = [{
            "productId": f"p-var-{i}", "name": f"Product {i}",
            "price": 10.0, "archived": value,
        } for i, (value, _e) in enumerate(cases)]
        self._run(records)
        for i, (_value, expected) in enumerate(cases):
            self.assertEqual(
                Product.objects.get(external_id=f"p-var-{i}").active,
                expected)

    def test_archived_junk_is_skipped_not_guessed(self):
        for junk in ("maybe", "", None, 2):
            with self.subTest(junk=junk):
                out = self._run([{
                    "productId": "p-junk", "name": "Junk Product",
                    "price": 10.0, "archived": junk,
                }])
                self.assertIn("'created': 0", out)
                self.assertIn("'skipped': 1", out)
                self.assertEqual(Product.objects.count(), 0)

    def test_int_ids_import_as_strings(self):
        # TF-5 regression: int productId/code/barcode sliced with
        # [:64] raised TypeError and aborted the whole import.
        out = self._run([{
            "productId": 101, "name": "Int Id Product",
            "code": 11511, "barcode": 123456789012,
            "price": 10.0, "archived": False,
        }])
        self.assertIn("'created': 1", out)
        self.assertIn("'skipped': 0", out)
        product = Product.objects.get(external_id="101")
        self.assertIsInstance(product.external_id, str)
        self.assertEqual(product.sku, "11511")
        self.assertIsInstance(product.sku, str)
        self.assertEqual(product.barcode, "123456789012")
        self.assertIsInstance(product.barcode, str)

    def test_dict_code_is_skipped_and_import_completes(self):
        # TF-5: a dict-valued code cannot be stringified as an id —
        # counted skipped, zero products, import completes.
        out = self._run([{
            "productId": "p-dict-code", "name": "Dict Code Product",
            "code": {"bad": 1}, "barcode": "123",
            "price": 10.0, "archived": False,
        }])
        self.assertIn("'created': 0", out)
        self.assertIn("'skipped': 1", out)
        self.assertEqual(Product.objects.count(), 0)

    def test_unstringifiable_id_fields_are_skipped(self):
        cases = [
            {"productId": {"bad": 1}, "name": "Dict Id"},
            {"productId": ["p-1"], "name": "List Id"},
            {"productId": "p-ok-1", "name": "Dict Barcode",
             "barcode": {"bad": 1}},
            {"productId": "p-ok-2", "name": "List Code",
             "code": ["11511"]},
        ]
        for record in cases:
            with self.subTest(record=record):
                record.setdefault("price", 10.0)
                out = self._run([record])
                self.assertIn("'created': 0", out)
                self.assertIn("'skipped': 1", out)
                self.assertEqual(Product.objects.count(), 0)

    def test_missing_price_is_skipped_never_zero(self):
        # TF-8: price is required (Product.price is not nullable).
        # Missing/empty/unparseable price = counted skip, reported
        # as skipped_missing_price — never imported as 0.00 while a
        # missing reorderCost imports as cost_price=None.
        variants = [
            {"productId": "p-np-1", "name": "No Price Key"},
            {"productId": "p-np-2", "name": "Null Price", "price": None},
            {"productId": "p-np-3", "name": "Empty Price", "price": ""},
            {"productId": "p-np-4", "name": "Bad Price", "price": "abc"},
        ]
        for record in variants:
            with self.subTest(record=record):
                out = self._run([record])
                self.assertIn("'created': 0", out)
                self.assertIn("'skipped': 1", out)
                self.assertIn("'skipped_missing_price': 1", out)
                self.assertEqual(Product.objects.count(), 0)

    def test_missing_price_skip_does_not_block_others(self):
        out = self._run([
            {"productId": "p-np", "name": "No Price"},
            {"productId": "p-ok", "name": "Priced", "price": 5.0,
             "reorderCost": None},
        ])
        self.assertIn("'created': 1", out)
        self.assertIn("'skipped_missing_price': 1", out)
        product = Product.objects.get(external_id="p-ok")
        self.assertEqual(product.price, Decimal("5.00"))
        # The nullable field keeps its distinct behaviour: a
        # missing cost is None, not 0.00 and not a skip.
        self.assertIsNone(product.cost_price)

    def test_explicit_zero_price_imports_as_zero(self):
        # A present 0 is a usable price, distinct from missing.
        out = self._run([{
            "productId": "p-free", "name": "Free Sample", "price": 0,
        }])
        self.assertIn("'created': 1", out)
        self.assertIn("'skipped_missing_price': 0", out)
        self.assertEqual(
            Product.objects.get(external_id="p-free").price,
            Decimal("0.00"))

    def test_fractional_quantity_is_skipped_not_truncated(self):
        # TF-8: int(2.9) silently became 2 under the old code.
        for value in (2.9, "2.9", 0.5, "lots", True, [6]):
            with self.subTest(value=value):
                out = self._run([{
                    "productId": "p-frac", "name": "Fractional",
                    "price": 10.0, "quantityInStock": value,
                }])
                self.assertIn("'created': 0", out)
                self.assertIn("'skipped': 1", out)
                self.assertEqual(Product.objects.count(), 0)
                self.assertEqual(StockMovement.objects.count(), 0)

    def test_integral_quantity_forms_import(self):
        cases = [(6, 6), (6.0, 6), ("6", 6), (0, 0), (None, 0)]
        records = [{
            "productId": f"p-qty-{i}", "name": f"Qty {i}",
            "price": 10.0, "quantityInStock": value,
        } for i, (value, _e) in enumerate(cases)]
        records.append({
            "productId": "p-qty-absent", "name": "Qty Absent",
            "price": 10.0,
        })
        out = self._run(records)
        self.assertIn("'created': 6", out)
        self.assertIn("'skipped': 0", out)
        for i, (_value, expected) in enumerate(cases):
            self.assertEqual(
                Product.objects.get(
                    external_id=f"p-qty-{i}").current_stock, expected)
        self.assertEqual(
            Product.objects.get(
                external_id="p-qty-absent").current_stock, 0)

    def test_money_parsing_matches_price_book_decimal(self):
        # TF-8: the same input must yield the same Decimal in both
        # importers — _money here mirrors import_price_book._decimal
        # (Decimal(str(value)), no local quantize).
        from saloncore.management.commands.import_price_book import (
            _decimal as price_book_decimal,
        )
        from saloncore.management.commands.import_products import _money

        samples = [38, 38.0, "38.0", 12.75, "10.005", "10.004",
                   "19.999", "0.10", "7", None, "", "not-money"]
        for value in samples:
            with self.subTest(value=value):
                mine, theirs = _money(value), price_book_decimal(value)
                self.assertEqual(mine, theirs)
                if mine is not None:
                    self.assertEqual(mine.as_tuple(), theirs.as_tuple())

    def test_external_id_unique_when_present(self):
        self._run()
        with self.assertRaises(Exception):
            Product.objects.create(
                salon=Salon.objects.get(name="Test Salon"),
                external_id="p-1", name="Dupe", price=Decimal("1.00"),
            )
