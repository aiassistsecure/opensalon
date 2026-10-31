import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from catalog.models import Product, StockMovement
from catalog.movement_export import (
    MOVEMENT_FIELDNAMES,
    TOTAL_FIELDNAMES,
    export_movement_export,
    export_movements,
    movement_totals,
)
from saloncore.models import Salon


class MovementExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.day = date(2026, 10, 3)

    def make_product(self, name, sku="", barcode="", salon=None):
        return Product.objects.create(
            salon=salon or self.salon, name=name, sku=sku,
            barcode=barcode, price=Decimal("10.00"),
        )

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE,
             note="", on=None):
        movement = StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta, note=note,
        )
        if on is not None:
            moment = timezone.make_aware(
                datetime(on.year, on.month, on.day, 12, 0)
            )
            StockMovement.objects.filter(pk=movement.pk).update(
                created_at=moment
            )
            movement.created_at = moment
        return movement

    def test_exports_core_fields(self):
        p = self.make_product("Shampoo", sku="SH-001", barcode="0123")
        m = self.move(p, 10, note="delivery", on=self.day)
        (record,) = export_movements(self.salon, self.day, self.day)
        self.assertEqual(list(record), MOVEMENT_FIELDNAMES)
        self.assertEqual(record["id"], m.pk)
        self.assertEqual(record["product_id"], p.pk)
        self.assertEqual(record["product_name"], "Shampoo")
        self.assertEqual(record["sku"], "SH-001")
        self.assertEqual(record["barcode"], "0123")
        self.assertEqual(record["quantity_delta"], 10)
        self.assertEqual(record["kind"], StockMovement.Kind.RECEIVE)
        self.assertEqual(record["note"], "delivery")
        self.assertEqual(record["created_at"], m.created_at.isoformat())
        self.assertEqual(json.loads(json.dumps(record)), record)

    def test_range_filtering_includes_whole_end_day(self):
        p = self.make_product("Shampoo")
        before = self.move(p, 1, on=self.day - timedelta(days=1))
        first = self.move(p, 2, on=self.day)
        last = self.move(p, 3, on=self.day + timedelta(days=1))
        after = self.move(p, 4, on=self.day + timedelta(days=2))
        rows = export_movements(
            self.salon, self.day, self.day + timedelta(days=1))
        self.assertEqual([r["id"] for r in rows], [first.pk, last.pk])
        self.assertNotIn(before.pk, [r["id"] for r in rows])
        self.assertNotIn(after.pk, [r["id"] for r in rows])

    def test_unbounded_and_other_salon(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        self.move(foreign, 9, on=self.day)
        own = self.make_product("Own")
        self.move(own, 5, on=self.day)
        rows = export_movements(self.salon)
        self.assertEqual([r["product_id"] for r in rows], [own.pk])

    def test_rollup_correctness(self):
        a = self.make_product("Alpha", sku="A-1", barcode="111")
        b = self.make_product("Beta", sku="B-1", barcode="222")
        self.move(a, 10, on=self.day)
        self.move(a, -3, kind=StockMovement.Kind.SALE, on=self.day)
        self.move(a, -1, kind=StockMovement.Kind.ADJUSTMENT, on=self.day)
        self.move(b, 4, on=self.day)
        self.move(b, 100, on=self.day + timedelta(days=5))  # out of range
        totals = movement_totals(self.salon, self.day, self.day)
        self.assertEqual([t["product_id"] for t in totals], [a.pk, b.pk])
        alpha, beta = totals
        self.assertEqual(list(alpha), TOTAL_FIELDNAMES)
        self.assertEqual(alpha["sku"], "A-1")
        self.assertEqual(alpha["barcode"], "111")
        self.assertEqual(alpha["movement_count"], 3)
        self.assertEqual(alpha["net_delta"], 6)
        self.assertEqual(alpha["by_kind"], {
            StockMovement.Kind.RECEIVE: 10,
            StockMovement.Kind.SALE: -3,
            StockMovement.Kind.ADJUSTMENT: -1,
        })
        self.assertEqual(beta["movement_count"], 1)
        self.assertEqual(beta["net_delta"], 4)
        # Rollup reconciles with the exported rows.
        rows = export_movements(self.salon, self.day, self.day)
        self.assertEqual(
            sum(t["net_delta"] for t in totals),
            sum(r["quantity_delta"] for r in rows),
        )

    def test_empty_range(self):
        p = self.make_product("Shampoo")
        self.move(p, 7, on=self.day)
        empty_day = self.day + timedelta(days=30)
        self.assertEqual(export_movements(self.salon, empty_day, empty_day), [])
        self.assertEqual(movement_totals(self.salon, empty_day, empty_day), [])
        combined = export_movement_export(self.salon, empty_day, empty_day)
        self.assertEqual(combined, {"movements": [], "totals": []})

    def test_combined_export_and_read_only(self):
        p = self.make_product("Shampoo")
        self.move(p, 5, on=self.day)
        combined = export_movement_export(self.salon, self.day, self.day)
        self.assertEqual(len(combined["movements"]), 1)
        self.assertEqual(combined["totals"][0]["net_delta"], 5)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(p.current_stock, 5)
