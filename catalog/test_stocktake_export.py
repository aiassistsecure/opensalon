import csv
import io
import json
from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.stocktake import compute_variances, reconcile_stocktake
from catalog.stocktake_export import (
    STOCKTAKE_FIELDNAMES,
    export_completed_stocktake_csv,
    export_stocktake_counts,
    export_stocktake_counts_csv,
)
from saloncore.models import Salon


class StocktakeExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, price="10.00", sku="", barcode="",
                     salon=None):
        return Product.objects.create(
            salon=salon or self.salon, name=name, sku=sku,
            barcode=barcode, price=Decimal(price),
        )

    def move(self, product, delta):
        return StockMovement.objects.create(
            product=product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=delta,
        )

    def test_csv_header(self):
        shampoo = self.make_product("Shampoo")
        self.move(shampoo, 5)
        text = export_stocktake_counts_csv(self.salon, {shampoo: 5})
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], STOCKTAKE_FIELDNAMES)
        self.assertEqual(
            STOCKTAKE_FIELDNAMES,
            ["reference", "product_id", "product_name", "sku",
             "barcode", "expected_stock", "counted_stock", "variance",
             "movement_id", "already_applied"],
        )

    def test_dry_run_rows_match_service_output(self):
        shampoo = self.make_product(
            "Shampoo", sku="SH-001", barcode="012345678905")
        self.move(shampoo, 10)
        serum = self.make_product("Serum", sku="SE-002")
        self.move(serum, 3)
        counts = {shampoo: 6, serum: 5}
        variances = compute_variances(self.salon, counts)
        records = export_stocktake_counts(self.salon, counts)
        self.assertEqual(json.loads(json.dumps(records)), records)
        self.assertEqual(len(records), len(variances))
        for record, variance in zip(records, variances):
            self.assertEqual(record["product_id"], variance.product.pk)
            self.assertEqual(record["expected_stock"],
                             variance.expected_stock)
            self.assertEqual(record["counted_stock"],
                             variance.counted_stock)
            self.assertEqual(record["variance"], variance.variance)
            self.assertIsNone(record["movement_id"])
            self.assertEqual(record["reference"], "")
            self.assertFalse(record["already_applied"])
        parsed = list(csv.DictReader(io.StringIO(
            export_stocktake_counts_csv(self.salon, counts))))
        self.assertEqual([r["product_name"] for r in parsed],
                         [r["product_name"] for r in records])
        self.assertEqual(parsed[0]["movement_id"], "")

    def test_completed_result_carries_reference_and_movement(self):
        shampoo = self.make_product("Shampoo")
        self.move(shampoo, 10)
        conditioner = self.make_product("Conditioner")
        self.move(conditioner, 4)
        result = reconcile_stocktake(
            self.salon, {shampoo: 6, conditioner: 4}, "STK-1")
        records = export_stocktake_counts(result)
        by_name = {r["product_name"]: r for r in records}
        self.assertEqual(by_name["Shampoo"]["reference"], "STK-1")
        self.assertEqual(by_name["Shampoo"]["variance"], -4)
        movement = StockMovement.objects.get(
            kind=StockMovement.Kind.STOCKTAKE)
        self.assertEqual(by_name["Shampoo"]["movement_id"], movement.pk)
        self.assertIsNone(by_name["Conditioner"]["movement_id"])
        self.assertFalse(by_name["Shampoo"]["already_applied"])
        parsed = list(csv.DictReader(io.StringIO(
            export_completed_stocktake_csv(result))))
        self.assertEqual(parsed[0]["reference"], "STK-1")
        # Re-running under the same reference flags already_applied.
        again = reconcile_stocktake(self.salon, {shampoo: 6}, "STK-1")
        self.assertTrue(export_stocktake_counts(again)[0]["already_applied"])

    def test_salon_isolation(self):
        shampoo = self.make_product("Shampoo")
        self.move(shampoo, 8)
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        self.move(foreign, 4)
        records = export_stocktake_counts(self.salon, {shampoo: 8})
        self.assertEqual([r["product_name"] for r in records], ["Shampoo"])
        with self.assertRaises(ValueError):
            export_stocktake_counts(self.salon, {foreign: 1})

    def test_empty_is_header_only(self):
        self.assertEqual(export_stocktake_counts(self.salon, {}), [])
        self.assertEqual(
            export_stocktake_counts_csv(self.salon, {}),
            ",".join(STOCKTAKE_FIELDNAMES) + "\n",
        )

    def test_alias_and_read_only(self):
        shampoo = self.make_product("Shampoo")
        self.move(shampoo, 4)
        before = StockMovement.objects.count()
        self.assertEqual(
            export_completed_stocktake_csv(self.salon, {shampoo: 3}),
            export_stocktake_counts_csv(self.salon, {shampoo: 3}),
        )
        export_stocktake_counts(self.salon, {shampoo: 3})
        self.assertEqual(StockMovement.objects.count(), before)
        self.assertEqual(shampoo.current_stock, 4)

    def test_invalid_counts_still_raise_service_error(self):
        shampoo = self.make_product("Shampoo")
        self.move(shampoo, 2)
        with self.assertRaises(ValueError):
            export_stocktake_counts_csv(self.salon, {shampoo: -1})
