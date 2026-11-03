from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.update_product import update_product, validate_update_product
from saloncore.models import Salon


class UpdateProductTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("24.00"),
            external_id="src-1", payload={"src": 1})

    def snapshot(self):
        self.product.refresh_from_db()
        p = self.product
        return (p.name, p.sku, p.barcode, p.price, p.active,
                p.external_id, p.payload)

    def test_updates_all_fields(self):
        p = update_product(
            self.salon, self.product, name="  Conditioner  ",
            price="26.50", sku="CO-001", barcode="012345678906",
            active=False)
        self.assertEqual(
            (p.name, p.sku, p.barcode, p.price, p.active),
            ("Conditioner", "CO-001", "012345678906",
             Decimal("26.50"), False))
        self.assertEqual(self.snapshot()[0], "Conditioner")

    def test_partial_update_leaves_omitted_fields_unchanged(self):
        update_product(self.salon, self.product, price="30.00")
        self.assertEqual(
            self.snapshot(),
            ("Shampoo", "SH-001", "012345678905", Decimal("30.00"),
             True, "src-1", {"src": 1}))

    def test_clearing_sku_and_barcode_with_empty_string(self):
        update_product(self.salon, self.product, sku="", barcode="")
        self.assertEqual(self.snapshot()[1:3], ("", ""))

    def test_no_fields_refused_nothing_written(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            update_product(self.salon, self.product)
        self.assertEqual(self.snapshot(), before)

    def test_keeping_own_barcode_allowed(self):
        p = update_product(
            self.salon, self.product, barcode="012345678905",
            name="Renamed")
        self.assertEqual(p.barcode, "012345678905")

    def test_duplicate_barcode_other_product_refused(self):
        Product.objects.create(
            salon=self.salon, name="Other", barcode="999",
            price=Decimal("1.00"))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            update_product(self.salon, self.product, barcode="999")
        self.assertEqual(self.snapshot(), before)

    def test_barcode_used_in_other_salon_allowed(self):
        Product.objects.create(
            salon=self.other, name="Other", barcode="999",
            price=Decimal("1.00"))
        update_product(self.salon, self.product, barcode="999")
        self.assertEqual(self.snapshot()[2], "999")

    def test_cross_salon_and_unsaved_refused(self):
        before = self.snapshot()
        for salon, product in (
                (self.other, self.product),
                (Salon(name="Unsaved"), self.product),
                (self.salon, Product(name="Unsaved"))):
            with self.assertRaises(ValueError):
                update_product(salon, product, name="X")
        self.assertEqual(self.snapshot(), before)

    def test_invalid_values_refused_nothing_written(self):
        before = self.snapshot()
        for kwargs in ({"name": "  "}, {"name": "x" * 161},
                       {"name": 123}, {"price": "abc"},
                       {"price": "-1.00"}, {"price": ""},
                       {"sku": "s" * 65}, {"barcode": "b" * 65},
                       {"active": "yes"}):
            with self.assertRaises(ValueError):
                update_product(self.salon, self.product, **kwargs)
        self.assertEqual(self.snapshot(), before)

    def test_stock_and_source_identity_untouched(self):
        StockMovement.objects.create(
            product=self.product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=7)
        update_product(
            self.salon, self.product, name="Renamed", price="9.00")
        self.assertEqual(self.product.current_stock, 7)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(self.snapshot()[5:], ("src-1", {"src": 1}))
        with self.assertRaises(TypeError):
            update_product(
                self.salon, self.product, external_id="src-2")

    def test_validate_writes_nothing_and_returns_only_given(self):
        cleaned = validate_update_product(
            self.salon, self.product, name="  New  ", price="1.50")
        self.assertEqual(
            cleaned["name"], "New")
        self.assertEqual(cleaned["price"], Decimal("1.50"))
        self.assertNotIn("sku", cleaned)
        self.assertNotIn("active", cleaned)
        self.assertEqual(self.snapshot()[0], "Shampoo")

    def test_validate_same_errors_writes_nothing(self):
        Product.objects.create(
            salon=self.salon, name="Other", barcode="999",
            price=Decimal("1.00"))
        before = self.snapshot()
        for kwargs in ({}, {"name": " "}, {"price": "-1.00"},
                       {"barcode": "999"}, {"active": 1}):
            with self.assertRaises(ValueError):
                validate_update_product(
                    self.salon, self.product, **kwargs)
        self.assertEqual(self.snapshot(), before)
