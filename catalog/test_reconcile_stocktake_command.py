"""Tests for the catalog reconcile_stocktake management command.

The command is a thin wrapper around
``catalog.stocktake.reconcile_stocktake``; these tests check
delegation (the printed JSON describes the result the service
returned and stock is reconciled to the counts), salon scoping,
idempotency per reference, and clean failure for bad input.
"""
import io
import json
from decimal import Decimal

from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.models import Product, StockMovement
from saloncore.models import Salon


class ReconcileStocktakeCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.shampoo = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        self.move(self.shampoo, 10)
        self.serum = Product.objects.create(
            salon=self.salon, name="Serum", sku="SE-002",
            barcode="222333444555", price=Decimal("19.99"))
        self.move(self.serum, 3)
        self.foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))
        self.move(self.foreign, 9)
        self.counts = {self.shampoo.pk: 6, self.serum.pk: 5}

    def move(self, product, delta):
        return StockMovement.objects.create(
            product=product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=delta)

    def stocktake_movements(self):
        return StockMovement.objects.filter(
            kind=StockMovement.Kind.STOCKTAKE)

    def run_command(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("reference", "STK-1")
        kwargs.setdefault("counts", self.counts)
        call_command("reconcile_stocktake", stdout=out, **kwargs)
        return out.getvalue()

    def test_command_is_registered_to_catalog(self):
        self.assertEqual(
            get_commands()["reconcile_stocktake"], "catalog")

    def test_stdout_describes_result_and_reconciles_stock(self):
        text = self.run_command()
        payload = json.loads(text)
        self.assertEqual(payload["reference"], "STK-1")
        self.assertFalse(payload["already_applied"])
        self.assertTrue(payload["has_variance"])
        by_name = {v["product_name"]: v for v in payload["variances"]}
        self.assertEqual(
            (by_name["Shampoo"]["expected_stock"],
             by_name["Shampoo"]["counted_stock"],
             by_name["Shampoo"]["variance"]), (10, 6, -4))
        self.assertEqual(
            (by_name["Serum"]["expected_stock"],
             by_name["Serum"]["counted_stock"],
             by_name["Serum"]["variance"]), (3, 5, 2))
        self.assertIsNotNone(by_name["Shampoo"]["movement_id"])
        self.assertNotIn("Foreign", text)
        # Both varying products reconciled; stock now == counts.
        self.assertEqual(self.stocktake_movements().count(), 2)
        self.assertEqual(self.shampoo.current_stock, 6)
        self.assertEqual(self.serum.current_stock, 5)
        notes = set(self.stocktake_movements().values_list(
            "note", flat=True))
        self.assertEqual(notes, {"Stocktake STK-1"})

    def test_count_and_reference_flags_reconcile(self):
        out = io.StringIO()
        call_command(
            "reconcile_stocktake", "--salon-id", str(self.salon.pk),
            "--reference", "STK-FLAGS",
            "--count", f"{self.shampoo.pk}=6",
            "--count", f"{self.serum.pk}=5", stdout=out)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["reference"], "STK-FLAGS")
        self.assertEqual(self.shampoo.current_stock, 6)
        self.assertEqual(self.serum.current_stock, 5)

    def test_rerun_with_same_reference_is_idempotent(self):
        first = json.loads(self.run_command())
        count_after_first = StockMovement.objects.count()
        second = json.loads(self.run_command())
        self.assertFalse(first["already_applied"])
        self.assertTrue(second["already_applied"])
        self.assertEqual(StockMovement.objects.count(), count_after_first)
        self.assertEqual(
            [v["variance"] for v in second["variances"]],
            [v["variance"] for v in first["variances"]])
        self.assertEqual(self.shampoo.current_stock, 6)

    def test_zero_variance_records_nothing(self):
        payload = json.loads(self.run_command(
            reference="STK-ZERO", counts={self.shampoo.pk: 10}))
        self.assertFalse(payload["has_variance"])
        self.assertEqual(payload["variances"][0]["variance"], 0)
        self.assertIsNone(payload["variances"][0]["movement_id"])
        self.assertEqual(self.stocktake_movements().count(), 0)

    def test_counts_may_use_scan_codes_programmatically(self):
        payload = json.loads(self.run_command(
            reference="STK-CODE", counts={"SH-001": 8}))
        self.assertEqual(payload["variances"][0]["product_id"],
                         self.shampoo.pk)
        self.assertEqual(self.shampoo.current_stock, 8)

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_command(salon_id=999999)
        self.assertEqual(self.stocktake_movements().count(), 0)

    def test_blank_or_missing_reference_raises_command_error(self):
        for reference in ("", "  ", None):
            with self.assertRaises(CommandError):
                self.run_command(reference=reference)
        self.assertEqual(self.stocktake_movements().count(), 0)

    def test_no_counts_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_command(counts=None)
        with self.assertRaises(CommandError):
            self.run_command(counts={})
        self.assertEqual(self.stocktake_movements().count(), 0)

    def test_foreign_count_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_command(counts={self.foreign.pk: 1})
        self.assertEqual(self.stocktake_movements().count(), 0)

    def test_unknown_product_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_command(counts={999999: 1})
        self.assertEqual(self.stocktake_movements().count(), 0)

    def test_negative_count_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_command(counts={self.shampoo.pk: -1})
        self.assertEqual(self.stocktake_movements().count(), 0)
        self.assertEqual(self.shampoo.current_stock, 10)

    def test_duplicate_count_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_command(counts=[
                f"{self.shampoo.pk}=6", f"{self.shampoo.pk}=7"])
        self.assertEqual(self.stocktake_movements().count(), 0)

    def test_invalid_count_string_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_command(counts=["not-a-count"])
        self.assertEqual(self.stocktake_movements().count(), 0)
