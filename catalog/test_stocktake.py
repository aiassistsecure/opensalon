from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.stocktake import (
    StocktakeResult,
    Variance,
    compute_variances,
    reconcile_stocktake,
)
from saloncore.models import Salon


class StocktakeTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.shampoo = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("24.00"),
        )
        self.conditioner = Product.objects.create(
            salon=self.salon, name="Conditioner", sku="CO-001",
            barcode="012345678906", price=Decimal("26.00"),
        )
        for product, qty in ((self.shampoo, 10), (self.conditioner, 4)):
            StockMovement.objects.create(
                product=product, kind=StockMovement.Kind.RECEIVE,
                quantity_delta=qty,
            )

    def stocktake_movements(self):
        return StockMovement.objects.filter(kind=StockMovement.Kind.STOCKTAKE)

    def test_variance_list_and_reconciling_movements(self):
        result = reconcile_stocktake(
            self.salon, {self.shampoo: 6, self.conditioner: 4}, "STK-1"
        )
        self.assertIsInstance(result, StocktakeResult)
        self.assertFalse(result.already_applied)
        self.assertTrue(result.has_variance)
        by_name = {v.product.name: v for v in result.variances}
        self.assertEqual(
            (by_name["Shampoo"].expected_stock, by_name["Shampoo"].counted_stock,
             by_name["Shampoo"].variance),
            (10, 6, -4),
        )
        self.assertEqual(by_name["Shampoo"].derived_stock, 10)
        self.assertEqual(by_name["Shampoo"].difference, -4)
        self.assertEqual(by_name["Conditioner"].variance, 0)
        # Only the varying product gets a movement; stock now == count.
        self.assertEqual(self.stocktake_movements().count(), 1)
        movement = self.stocktake_movements().get()
        self.assertEqual(movement.quantity_delta, -4)
        self.assertEqual(movement.note, "Stocktake STK-1")
        self.assertEqual(result.movements, (movement,))
        self.assertEqual(self.shampoo.current_stock, 6)
        self.assertEqual(self.conditioner.current_stock, 4)

    def test_positive_variance_adds_stock(self):
        result = reconcile_stocktake(self.salon, {self.shampoo: 13}, "STK-2")
        self.assertEqual(result.variances[0].variance, 3)
        self.assertEqual(self.shampoo.current_stock, 13)

    def test_counts_may_use_ids_and_scan_codes(self):
        result = reconcile_stocktake(
            self.salon,
            {self.shampoo.pk: 9, "012345678906": 2},
            "STK-3",
        )
        self.assertEqual(self.shampoo.current_stock, 9)
        self.assertEqual(self.conditioner.current_stock, 2)
        by_sku = reconcile_stocktake(self.salon, {"CO-001": 5}, "STK-3b")
        self.assertEqual(by_sku.variances[0].product, self.conditioner)
        self.assertEqual(self.conditioner.current_stock, 5)

    def test_idempotent_per_reference(self):
        first = reconcile_stocktake(self.salon, {self.shampoo: 6}, "STK-4")
        count_after_first = StockMovement.objects.count()
        second = reconcile_stocktake(self.salon, {self.shampoo: 6}, "STK-4")
        self.assertFalse(first.already_applied)
        self.assertTrue(second.already_applied)
        self.assertEqual(StockMovement.objects.count(), count_after_first)
        self.assertEqual(second.variances[0].variance, -4)
        self.assertEqual(second.variances[0].expected_stock, 10)
        self.assertEqual(second.movements, first.movements)
        self.assertEqual(self.shampoo.current_stock, 6)

    def test_new_reference_reconciles_again(self):
        reconcile_stocktake(self.salon, {self.shampoo: 6}, "STK-5")
        result = reconcile_stocktake(self.salon, {self.shampoo: 3}, "STK-6")
        self.assertFalse(result.already_applied)
        self.assertEqual(result.variances[0].variance, -3)
        self.assertEqual(self.shampoo.current_stock, 3)

    def test_zero_variance_stocktake_records_nothing(self):
        result = reconcile_stocktake(self.salon, {self.shampoo: 10}, "STK-7")
        self.assertFalse(result.has_variance)
        self.assertEqual(self.stocktake_movements().count(), 0)
        again = reconcile_stocktake(self.salon, {self.shampoo: 10}, "STK-7")
        self.assertEqual(self.stocktake_movements().count(), 0)
        self.assertEqual(again.variances[0].variance, 0)

    def test_compute_variances_is_a_dry_run(self):
        variances = compute_variances(self.salon, {self.shampoo: 0})
        self.assertEqual(len(variances), 1)
        self.assertIsInstance(variances[0], Variance)
        self.assertEqual(variances[0].variance, -10)
        self.assertIsNone(variances[0].movement)
        self.assertEqual(self.stocktake_movements().count(), 0)
        self.assertEqual(self.shampoo.current_stock, 10)

    def test_stock_stays_derived_from_movements(self):
        reconcile_stocktake(
            self.salon, {self.shampoo: 7, self.conditioner: 9}, "STK-8"
        )
        self.assertEqual(self.shampoo.current_stock, 7)
        self.assertEqual(self.conditioner.current_stock, 9)

    def test_invalid_inputs_raise_and_record_nothing(self):
        bad_calls = [
            lambda: reconcile_stocktake(self.salon, {self.shampoo: 1}, ""),
            lambda: reconcile_stocktake(self.salon, {self.shampoo: 1}, "  "),
            lambda: reconcile_stocktake(self.salon, {self.shampoo: -1}, "STK-9"),
            lambda: reconcile_stocktake(self.salon, {self.shampoo: True}, "STK-9"),
            lambda: reconcile_stocktake(self.salon, {}, "STK-9"),
            lambda: reconcile_stocktake(self.salon, {"999999999999": 1}, "STK-9"),
            lambda: reconcile_stocktake(self.salon, {99999: 1}, "STK-9"),
            lambda: reconcile_stocktake(
                self.salon, {self.shampoo: 1, "SH-001": 1}, "STK-9"
            ),
        ]
        for call in bad_calls:
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(self.stocktake_movements().count(), 0)

    def test_other_salons_product_is_rejected(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = Product.objects.create(
            salon=other, name="Foreign", price=Decimal("10.00")
        )
        with self.assertRaises(ValueError):
            reconcile_stocktake(self.salon, {foreign: 1}, "STK-10")
        with self.assertRaises(ValueError):
            reconcile_stocktake(other, {self.shampoo.barcode: 1}, "STK-10")
        self.assertEqual(self.stocktake_movements().count(), 0)
