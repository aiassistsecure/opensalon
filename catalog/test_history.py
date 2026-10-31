from decimal import Decimal

from django.test import TestCase

from catalog.history import HistoryEntry, StockHistory, product_history, stock_history
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class StockHistoryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, salon=None):
        return Product.objects.create(
            salon=salon or self.salon,
            name=name,
            price=Decimal("24.00"),
        )

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE, note=""):
        return StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta, note=note
        )

    def test_entries_chronological_with_running_balance(self):
        product = self.make_product("Shampoo")
        m1 = self.move(product, 10, note="delivery")
        m2 = self.move(product, -3, kind=StockMovement.Kind.SALE)
        m3 = self.move(product, -2, kind=StockMovement.Kind.ADJUSTMENT, note="damaged")
        m4 = self.move(product, 5, kind=StockMovement.Kind.STOCKTAKE)
        result = stock_history(self.salon, product)
        self.assertIsInstance(result, StockHistory)
        self.assertEqual(result.product, product)
        self.assertEqual(result.salon_id, self.salon.pk)
        self.assertEqual([e.movement for e in result.entries], [m1, m2, m3, m4])
        self.assertEqual([e.quantity_delta for e in result.entries], [10, -3, -2, 5])
        self.assertEqual([e.delta for e in result.entries], [10, -3, -2, 5])
        self.assertEqual([e.running_balance for e in result.entries], [10, 7, 5, 10])
        self.assertEqual([e.balance for e in result.entries], [10, 7, 5, 10])
        self.assertEqual([e.balance_after for e in result.entries], [10, 7, 5, 10])
        self.assertTrue(all(isinstance(e, HistoryEntry) for e in result.entries))
        self.assertEqual(result.entries[0].kind, StockMovement.Kind.RECEIVE)
        self.assertEqual(result.entries[0].note, "delivery")
        self.assertEqual(result.entries[2].note, "damaged")
        self.assertIsNotNone(result.entries[0].created_at)

    def test_final_balance_equals_derived_current_stock(self):
        product = self.make_product("Conditioner")
        self.move(product, 8)
        self.move(product, -8, kind=StockMovement.Kind.SALE)
        result = stock_history(self.salon, product)
        self.assertEqual(result.final_balance, 0)
        self.assertEqual(result.current_stock, product.current_stock)
        self.assertEqual(result.on_hand, 0)
        self.assertEqual(result.movement_count, 2)
        self.assertEqual(len(result), 2)
        self.assertEqual([e.movement for e in result], [e.movement for e in result.entries])

    def test_product_with_no_movements_has_empty_history(self):
        product = self.make_product("Never Stocked")
        result = stock_history(self.salon, product)
        self.assertEqual(result.entries, ())
        self.assertEqual(result.final_balance, 0)
        self.assertEqual(result.movement_count, 0)

    def test_negative_running_balance_is_not_clamped(self):
        product = self.make_product("Sold First")
        self.move(product, -2, kind=StockMovement.Kind.SALE)
        self.move(product, 10)
        result = stock_history(self.salon, product)
        self.assertEqual([e.running_balance for e in result.entries], [-2, 8])
        self.assertEqual(result.final_balance, 8)

    def test_only_this_products_movements_are_included(self):
        product = self.make_product("Own")
        other_product = self.make_product("Other Product")
        self.move(product, 4)
        self.move(other_product, 99)
        result = stock_history(self.salon, product)
        self.assertEqual([e.quantity_delta for e in result.entries], [4])

    def test_product_of_another_salon_raises(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        self.move(foreign, 6)
        with self.assertRaises(ValueError):
            stock_history(self.salon, foreign)
        # Its own salon can read it fine.
        self.assertEqual(stock_history(other, foreign).final_balance, 6)

    def test_product_id_resolved_within_salon(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        own = self.make_product("Own")
        self.move(own, 3)
        result = stock_history(self.salon, own.pk)
        self.assertEqual(result.product, own)
        self.assertEqual(result.final_balance, 3)
        with self.assertRaises(ValueError):
            stock_history(self.salon, foreign.pk)
        with self.assertRaises(ValueError):
            stock_history(self.salon, 999999)

    def test_unsaved_or_invalid_product_raises(self):
        unsaved = Product(salon=self.salon, name="Unsaved", price=Decimal("1.00"))
        for bad in (unsaved, "Shampoo", True, None, 1.5):
            with self.assertRaises(ValueError):
                stock_history(self.salon, bad)

    def test_single_product_argument_uses_its_own_salon(self):
        product = self.make_product("Solo")
        self.move(product, 7)
        result = stock_history(product)
        self.assertEqual(result.salon_id, self.salon.pk)
        self.assertEqual(result.final_balance, 7)
        self.assertEqual(product_history(self.salon, product).final_balance, 7)

    def test_history_is_read_only(self):
        product = self.make_product("Untouched")
        self.move(product, 5)
        before = StockMovement.objects.count()
        stock_history(self.salon, product)
        self.assertEqual(StockMovement.objects.count(), before)
