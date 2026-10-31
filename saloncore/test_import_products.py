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
    def _run(self):
        fh = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        )
        json.dump(RECORDS, fh)
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

    def test_external_id_unique_when_present(self):
        self._run()
        with self.assertRaises(Exception):
            Product.objects.create(
                salon=Salon.objects.get(name="Test Salon"),
                external_id="p-1", name="Dupe", price=Decimal("1.00"),
            )
