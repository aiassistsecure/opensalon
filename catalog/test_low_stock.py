from decimal import Decimal

from django.test import TestCase

from catalog.low_stock import DEFAULT_LOW_STOCK_THRESHOLD, LowStockRow, low_stock
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class LowStockTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, sku="", barcode="", salon=None):
        return Product.objects.create(
            salon=salon or self.salon,
            name=name,
            sku=sku,
            barcode=barcode,
            price=Decimal("24.00"),
        )

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE):
        return StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta
        )

    def test_on_hand_is_derived_from_movements(self):
        product = self.make_product("Shampoo", sku="SH-001", barcode="012345678905")
        self.move(product, 10)
        self.move(product, -7, kind=StockMovement.Kind.SALE)
        self.move(product, -1, kind=StockMovement.Kind.ADJUSTMENT)
        rows = low_stock(self.salon, threshold=5)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIsInstance(row, LowStockRow)
        self.assertEqual(row.product, product)
        self.assertEqual(row.sku, "SH-001")
        self.assertEqual(row.barcode, "012345678905")
        self.assertEqual(row.on_hand, 2)
        self.assertEqual(row.current_stock, 2)
        self.assertEqual(row.threshold, 5)
        self.assertEqual(row.reorder_threshold, 5)

    def test_product_at_threshold_is_included(self):
        product = self.make_product("At Threshold")
        self.move(product, 5)
        rows = low_stock(self.salon, threshold=5)
        self.assertEqual([row.product for row in rows], [product])
        self.assertEqual(rows[0].on_hand, 5)

    def test_product_above_threshold_is_excluded(self):
        product = self.make_product("Well Stocked")
        self.move(product, 6)
        self.assertEqual(low_stock(self.salon, threshold=5), [])
        # The same product qualifies under a higher threshold.
        rows = low_stock(self.salon, threshold=6)
        self.assertEqual([row.product for row in rows], [product])

    def test_product_with_no_movements_is_zero(self):
        product = self.make_product("Never Stocked")
        rows = low_stock(self.salon, threshold=5)
        self.assertEqual([row.product for row in rows], [product])
        self.assertEqual(rows[0].on_hand, 0)
        self.assertEqual(low_stock(self.salon, threshold=0)[0].on_hand, 0)

    def test_rows_ordered_by_on_hand_ascending(self):
        three = self.make_product("Three")
        self.move(three, 3)
        negative = self.make_product("Negative")
        self.move(negative, -2, kind=StockMovement.Kind.SALE)
        zero = self.make_product("Zero")
        one = self.make_product("One")
        self.move(one, 1)
        rows = low_stock(self.salon, threshold=5)
        self.assertEqual(
            [row.product for row in rows], [negative, zero, one, three]
        )
        self.assertEqual([row.on_hand for row in rows], [-2, 0, 1, 3])

    def test_default_threshold_applies_when_none_given(self):
        at_default = self.make_product("At Default")
        self.move(at_default, DEFAULT_LOW_STOCK_THRESHOLD)
        above_default = self.make_product("Above Default")
        self.move(above_default, DEFAULT_LOW_STOCK_THRESHOLD + 1)
        rows = low_stock(self.salon)
        self.assertEqual([row.product for row in rows], [at_default])
        self.assertEqual(rows[0].threshold, DEFAULT_LOW_STOCK_THRESHOLD)

    def test_only_the_given_salons_products_are_reported(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        own = self.make_product("Own")
        rows = low_stock(self.salon, threshold=5)
        self.assertEqual([row.product for row in rows], [own])
        rows = low_stock(other, threshold=5)
        self.assertEqual([row.product for row in rows], [foreign])

    def test_invalid_threshold_raises(self):
        for bad in (-1, True, 1.5, "5"):
            with self.assertRaises(ValueError):
                low_stock(self.salon, threshold=bad)
