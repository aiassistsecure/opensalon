from decimal import Decimal

from django.test import TestCase

from catalog.models import Product
from saloncore.models import Salon


class ProductModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def test_creation_and_salon_fk(self):
        product = Product.objects.create(
            salon=self.salon,
            name="Shampoo",
            sku="SH-001",
            price=Decimal("24.00"),
        )
        self.assertEqual(product.salon, self.salon)
        self.assertIn(product, list(self.salon.products.all()))
        self.assertEqual(product.sku, "SH-001")
        self.assertEqual(product.price, Decimal("24.00"))

    def test_barcode_stored_and_lookup(self):
        Product.objects.create(
            salon=self.salon,
            name="Conditioner",
            barcode="012345678905",
            price=Decimal("26.00"),
        )
        found = Product.objects.get(barcode="012345678905")
        self.assertEqual(found.name, "Conditioner")
        self.assertEqual(found.barcode, "012345678905")

    def test_defaults(self):
        product = Product.objects.create(
            salon=self.salon, name="Hair Mask", price=Decimal("30.00")
        )
        product.refresh_from_db()
        self.assertEqual(product.current_stock, 0)
        self.assertTrue(product.active)
        self.assertEqual(product.sku, "")
        self.assertEqual(product.barcode, "")

    def test_str_is_name(self):
        product = Product(salon=self.salon, name="Shampoo", price=Decimal("24.00"))
        self.assertEqual(str(product), "Shampoo")

    def test_ordering_by_name(self):
        Product.objects.create(
            salon=self.salon, name="Shampoo", price=Decimal("24.00")
        )
        Product.objects.create(
            salon=self.salon, name="Conditioner", price=Decimal("26.00")
        )
        Product.objects.create(
            salon=self.salon, name="Hair Mask", price=Decimal("30.00")
        )
        names = list(Product.objects.values_list("name", flat=True))
        self.assertEqual(names, ["Conditioner", "Hair Mask", "Shampoo"])
