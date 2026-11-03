"""Delegated-flag dry-run contract tests for catalog services.

The ``scan_receive`` / ``scan_sell`` / ``reconcile_stocktake``
commands are SAFE-by-flag: they delegate ``dry_run`` into
:mod:`catalog.scanning` and :mod:`catalog.stocktake`, whose
safety holds only while every write stays below the ``dry_run``
branch. Unlike team, catalog had no contract test pinning that
— a refactor moving a ``StockMovement`` create above the flag
check would silently turn every preview into a real write.

These tests pin the contract at the service level, modelled on
``team/test_dry_run_nedb_safe.py``:

- a dry run never calls ``StockMovement.objects.create``
  (mocked, so the tests fail loudly even on SQLite if a create
  ever moves above the flag check);
- a dry run writes nothing at all — movement/product counts,
  the product row, and derived stock are exactly as they were,
  and a dry stocktake does not consume its reference;
- a dry run returns the same would-be result the real path
  produces for the same inputs (kind/delta/note and resulting
  stock for scans; variance triples for stocktakes).

Fixtures are tiny synthetic records.
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.scanning import scan_receive, scan_sell
from catalog.stocktake import reconcile_stocktake
from saloncore.models import Salon


def _counts():
    return (Product.objects.count(), StockMovement.objects.count())


class Fixture(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Dry Salon")
        self.shampoo = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("24.00"))
        self.conditioner = Product.objects.create(
            salon=self.salon, name="Conditioner", sku="CO-001",
            barcode="012345678906", price=Decimal("26.00"))
        for product, qty in ((self.shampoo, 10), (self.conditioner, 4)):
            StockMovement.objects.create(
                product=product, kind=StockMovement.Kind.RECEIVE,
                quantity_delta=qty)
        self.before = _counts()


class ScanReceiveDryRunTests(Fixture):
    def test_dry_run_never_creates_and_writes_nothing(self):
        with mock.patch.object(
                StockMovement.objects, "create") as create:
            result = scan_receive(
                self.salon, "012345678905", quantity=5, dry_run=True)
        create.assert_not_called()
        self.assertTrue(result.found)
        self.assertEqual(result.product, self.shampoo)
        # The would-be movement rides along unsaved.
        self.assertIsNone(result.movement.pk)
        self.assertEqual(result.movement.kind, StockMovement.Kind.RECEIVE)
        self.assertEqual(result.movement.quantity_delta, 5)
        self.assertEqual(result.movement.note, "Barcode scan (receive)")
        self.assertEqual(result.current_stock, 15)
        self.assertFalse(result.below_zero)
        # Nothing written: counts, the product row, derived stock.
        self.assertEqual(_counts(), self.before)
        self.assertEqual(self.shampoo.current_stock, 10)
        self.shampoo.refresh_from_db()
        self.assertEqual(
            (self.shampoo.name, self.shampoo.sku, self.shampoo.price),
            ("Shampoo", "SH-001", Decimal("24.00")))

    def test_dry_run_result_matches_real_run(self):
        dry = scan_receive(
            self.salon, "012345678905", quantity=5, dry_run=True)
        real = scan_receive(self.salon, "012345678905", quantity=5)
        self.assertEqual(
            (dry.movement.kind, dry.movement.quantity_delta,
             dry.movement.note, dry.current_stock, dry.below_zero),
            (real.movement.kind, real.movement.quantity_delta,
             real.movement.note, real.current_stock, real.below_zero))
        self.assertIsNotNone(real.movement.pk)
        self.assertEqual(_counts(), (self.before[0], self.before[1] + 1))
        self.assertEqual(self.shampoo.current_stock, 15)

    def test_dry_run_resolves_sku_like_the_real_path(self):
        result = scan_receive(self.salon, "SH-001", quantity=2, dry_run=True)
        self.assertTrue(result.found)
        self.assertEqual(result.product, self.shampoo)
        self.assertEqual(result.current_stock, 12)
        self.assertEqual(_counts(), self.before)


class ScanSellDryRunTests(Fixture):
    def test_dry_run_never_creates_and_writes_nothing(self):
        with mock.patch.object(
                StockMovement.objects, "create") as create:
            result = scan_sell(
                self.salon, "012345678905", quantity=3, dry_run=True)
        create.assert_not_called()
        self.assertTrue(result.found)
        self.assertIsNone(result.movement.pk)
        self.assertEqual(result.movement.kind, StockMovement.Kind.SALE)
        self.assertEqual(result.movement.quantity_delta, -3)
        self.assertEqual(result.movement.note, "Barcode scan (sale)")
        self.assertEqual(result.current_stock, 7)
        self.assertFalse(result.below_zero)
        self.assertEqual(_counts(), self.before)
        self.assertEqual(self.shampoo.current_stock, 10)

    def test_dry_run_below_zero_matches_real_run(self):
        dry = scan_sell(
            self.salon, "012345678905", quantity=12, dry_run=True)
        self.assertEqual(dry.current_stock, -2)
        self.assertTrue(dry.below_zero)
        self.assertEqual(_counts(), self.before)
        self.assertEqual(self.shampoo.current_stock, 10)
        real = scan_sell(self.salon, "012345678905", quantity=12)
        self.assertEqual(
            (dry.movement.kind, dry.movement.quantity_delta,
             dry.current_stock, dry.below_zero),
            (real.movement.kind, real.movement.quantity_delta,
             real.current_stock, real.below_zero))
        self.assertEqual(self.shampoo.current_stock, -2)

    def test_dry_run_unknown_code_never_creates(self):
        with mock.patch.object(
                StockMovement.objects, "create") as create:
            for func in (scan_receive, scan_sell):
                result = func(
                    self.salon, "999999999999", dry_run=True)
                self.assertFalse(result.found)
                self.assertIsNone(result.product)
                self.assertIsNone(result.movement)
                self.assertIsNone(result.current_stock)
        create.assert_not_called()
        self.assertEqual(_counts(), self.before)

    def test_dry_run_invalid_quantity_raises_and_writes_nothing(self):
        for func in (scan_receive, scan_sell):
            with self.assertRaises(ValueError):
                func(self.salon, "012345678905", quantity=0, dry_run=True)
        self.assertEqual(_counts(), self.before)


class ReconcileStocktakeDryRunTests(Fixture):
    def counts(self):
        return {self.shampoo: 6, self.conditioner: 4}

    @staticmethod
    def triples(result):
        return tuple(
            (v.product.pk, v.expected_stock, v.counted_stock, v.variance)
            for v in result.variances)

    def test_dry_run_never_creates_and_writes_nothing(self):
        with mock.patch.object(
                StockMovement.objects, "create") as create:
            result = reconcile_stocktake(
                self.salon, self.counts(), "STK-DRY", dry_run=True)
        create.assert_not_called()
        self.assertFalse(result.already_applied)
        self.assertEqual(
            self.triples(result),
            ((self.shampoo.pk, 10, 6, -4),
             (self.conditioner.pk, 4, 4, 0)))
        # Dry variances carry no movements at all.
        self.assertEqual(result.movements, ())
        self.assertTrue(
            all(v.movement is None for v in result.variances))
        self.assertEqual(_counts(), self.before)
        self.assertEqual(self.shampoo.current_stock, 10)
        self.assertEqual(self.conditioner.current_stock, 4)

    def test_dry_run_result_matches_real_run_and_keeps_reference(self):
        dry = reconcile_stocktake(
            self.salon, self.counts(), "STK-DRY", dry_run=True)
        real = reconcile_stocktake(self.salon, self.counts(), "STK-DRY")
        # The dry run did not consume the reference.
        self.assertFalse(real.already_applied)
        self.assertEqual(self.triples(dry), self.triples(real))
        self.assertEqual(len(real.movements), 1)
        movement = real.movements[0]
        self.assertEqual(movement.kind, StockMovement.Kind.STOCKTAKE)
        self.assertEqual(movement.quantity_delta, -4)
        self.assertEqual(movement.note, "Stocktake STK-DRY")
        self.assertEqual(self.shampoo.current_stock, 6)
        self.assertEqual(self.conditioner.current_stock, 4)

    def test_dry_run_on_applied_reference_attaches_no_movement(self):
        real = reconcile_stocktake(self.salon, self.counts(), "STK-APP")
        before = _counts()
        dry = reconcile_stocktake(
            self.salon, self.counts(), "STK-APP", dry_run=True)
        self.assertTrue(dry.already_applied)
        self.assertEqual(self.triples(dry), self.triples(real))
        self.assertEqual(dry.movements, ())
        self.assertTrue(
            all(v.movement is None for v in dry.variances))
        self.assertEqual(_counts(), before)
        # The real re-run still reports the original movement.
        again = reconcile_stocktake(self.salon, self.counts(), "STK-APP")
        self.assertTrue(again.already_applied)
        self.assertEqual(again.movements, real.movements)

    def test_dry_run_by_scan_code_matches_real_run(self):
        by_code = {"012345678905": 8}
        dry = reconcile_stocktake(
            self.salon, by_code, "STK-CODE", dry_run=True)
        real = reconcile_stocktake(self.salon, by_code, "STK-CODE")
        self.assertEqual(self.triples(dry), self.triples(real))
        self.assertEqual(self.triples(dry), ((self.shampoo.pk, 10, 8, -2),))
        self.assertEqual(self.shampoo.current_stock, 8)

    def test_dry_run_invalid_input_raises_and_writes_nothing(self):
        with self.assertRaises(ValueError):
            reconcile_stocktake(
                self.salon, {"999999999999": 1}, "STK-BAD", dry_run=True)
        with self.assertRaises(ValueError):
            reconcile_stocktake(
                self.salon, self.counts(), "  ", dry_run=True)
        self.assertEqual(_counts(), self.before)
        self.assertEqual(
            StockMovement.objects.filter(
                kind=StockMovement.Kind.STOCKTAKE).count(), 0)
