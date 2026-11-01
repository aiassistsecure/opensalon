from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from catalog.models import Product
from checkout.models import SaleItem
from checkout.sales import create_sale
from checkout.scan import add_scanned_product
from saloncore.models import Salon


class ScanToAddTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")
        self.product = Product.objects.create(
            salon=self.salon,
            name="Shampoo",
            price=Decimal("24.50"),
            barcode="5012345678900",
            sku="SHAM-001",
        )
        self.sale = create_sale(self.salon)

    def test_barcode_hit_adds_product_at_current_price(self):
        item = add_scanned_product(self.sale, "5012345678900")
        self.assertEqual(item.kind, SaleItem.Kind.PRODUCT)
        self.assertEqual(item.product, self.product)
        self.assertEqual(item.description, "Shampoo")
        self.assertEqual(item.quantity, 1)
        self.assertEqual(item.unit_price, Decimal("24.50"))
        self.assertEqual(self.sale.total, Decimal("24.50"))

    def test_sku_hit_adds_product_with_quantity(self):
        item = add_scanned_product(self.sale, "SHAM-001", quantity=2)
        self.assertEqual(item.product, self.product)
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.line_total, Decimal("49.00"))
        self.assertEqual(self.sale.items.count(), 1)

    def test_unknown_code_fails_closed_and_adds_nothing(self):
        with self.assertRaises(ValidationError):
            add_scanned_product(self.sale, "0000000000000")
        with self.assertRaises(ValidationError):
            add_scanned_product(self.sale, "  ")
        self.assertEqual(self.sale.items.count(), 0)
        self.assertEqual(self.sale.total, Decimal("0.00"))

    def test_cross_salon_product_is_rejected(self):
        Product.objects.create(
            salon=self.other_salon,
            name="Foreign Conditioner",
            price=Decimal("18.00"),
            barcode="5099999999999",
            sku="COND-999",
        )
        for code in ("5099999999999", "COND-999"):
            with self.assertRaises(ValidationError):
                add_scanned_product(self.sale, code)
        self.assertEqual(self.sale.items.count(), 0)

    def test_inactive_product_fails_closed_and_adds_nothing(self):
        Product.objects.create(
            salon=self.salon,
            name="Discontinued Wax",
            price=Decimal("12.00"),
            barcode="5088888888888",
            sku="WAX-888",
            active=False,
        )
        for code in ("5088888888888", "WAX-888"):
            with self.assertRaises(ValidationError):
                add_scanned_product(self.sale, code)
        self.assertEqual(self.sale.items.count(), 0)
