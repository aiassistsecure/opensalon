from decimal import Decimal

from django.test import TestCase

from catalog.add_product import add_product, validate_add_product
from catalog.models import Product
from saloncore.models import Salon


class AddProductTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def test_creates_product_with_all_fields(self):
        p = add_product(self.salon, "  Shampoo  ", "24.00",
                        sku="SH-001", barcode="012345678905")
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(
            (p.salon, p.name, p.sku, p.barcode, p.price, p.active),
            (self.salon, "Shampoo", "SH-001", "012345678905",
             Decimal("24.00"), True))

    def test_defaults_blank_codes_and_active(self):
        p = add_product(self.salon, "Conditioner", Decimal("26.50"))
        self.assertEqual((p.sku, p.barcode, p.active), ("", "", True))

    def test_inactive_product(self):
        p = add_product(self.salon, "Old Stock", "5.00", active=False)
        self.assertFalse(p.active)

    def test_zero_price_allowed(self):
        self.assertEqual(
            add_product(self.salon, "Sample", "0").price, Decimal("0"))

    def test_duplicate_barcode_same_salon_refused_nothing_written(self):
        add_product(self.salon, "Shampoo", "24.00",
                    barcode="012345678905")
        with self.assertRaises(ValueError):
            add_product(self.salon, "Copy", "24.00",
                        barcode="012345678905")
        self.assertEqual(Product.objects.count(), 1)

    def test_same_barcode_other_salon_allowed(self):
        add_product(self.salon, "Shampoo", "24.00",
                    barcode="012345678905")
        add_product(self.other, "Shampoo", "24.00",
                    barcode="012345678905")
        self.assertEqual(Product.objects.count(), 2)

    def test_blank_barcodes_not_unique_constrained(self):
        add_product(self.salon, "A", "1.00")
        add_product(self.salon, "B", "2.00", barcode="  ")
        self.assertEqual(Product.objects.count(), 2)

    def test_duplicate_sku_allowed_no_rule_on_sku(self):
        add_product(self.salon, "A", "1.00", sku="SH-001")
        add_product(self.salon, "B", "2.00", sku="SH-001")
        self.assertEqual(Product.objects.count(), 2)

    def test_blank_name_refused(self):
        for bad in ("", "   ", None, 123):
            with self.assertRaises(ValueError):
                add_product(self.salon, bad, "1.00")
        self.assertEqual(Product.objects.count(), 0)

    def test_overlong_name_sku_barcode_refused_not_truncated(self):
        for kwargs in ({"name": "x" * 161},
                       {"name": "Ok", "sku": "s" * 65},
                       {"name": "Ok", "barcode": "b" * 65}):
            with self.assertRaises(ValueError):
                add_product(self.salon, price="1.00", **kwargs)
        self.assertEqual(Product.objects.count(), 0)

    def test_bad_negative_and_missing_price_refused(self):
        for bad in (None, "", "abc", "-1.00", Decimal("-0.01")):
            with self.assertRaises(ValueError):
                add_product(self.salon, "Shampoo", bad)
        self.assertEqual(Product.objects.count(), 0)

    def test_unsaved_salon_refused(self):
        with self.assertRaises(ValueError):
            add_product(Salon(name="Unsaved"), "Shampoo", "1.00")
        self.assertEqual(Product.objects.count(), 0)

    def test_non_bool_active_refused(self):
        with self.assertRaises(ValueError):
            add_product(self.salon, "Shampoo", "1.00", active="yes")
        self.assertEqual(Product.objects.count(), 0)

    def test_validate_add_product_writes_nothing(self):
        cleaned = validate_add_product(
            self.salon, "  Shampoo  ", "24.00",
            sku="SH-001", barcode="012345678905")
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(
            (cleaned["name"], cleaned["sku"], cleaned["barcode"],
             cleaned["price"], cleaned["active"]),
            ("Shampoo", "SH-001", "012345678905",
             Decimal("24.00"), True))

    def test_validate_add_product_same_errors_writes_nothing(self):
        add_product(self.salon, "Existing", "10.00",
                    barcode="012345678905")
        before = Product.objects.count()
        for kwargs in ({"name": "  ", "price": "1.00"},
                       {"name": "X", "price": "abc"},
                       {"name": "X", "price": "-1.00"},
                       {"name": "Copy", "price": "1.00",
                        "barcode": "012345678905"},
                       {"name": "x" * 161, "price": "1.00"}):
            with self.assertRaises(ValueError):
                validate_add_product(self.salon, **kwargs)
        self.assertEqual(Product.objects.count(), before)
