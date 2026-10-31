import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from catalog.models import Product, StockMovement
from catalog.movement_summary import (
    PRODUCT_FIELDNAMES,
    movement_summary,
    net_change_by_product,
    stock_movement_summary,
    totals_by_kind,
    totals_by_product,
)
from saloncore.models import Salon


class MovementSummaryTests(TestCase):
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

    def seed(self):
        a = self.make_product("Alpha", sku="A-1", barcode="111")
        b = self.make_product("Beta", sku="B-1", barcode="222")
        self.move(a, 10, on=self.day)
        self.move(a, -3, kind=StockMovement.Kind.SALE, on=self.day)
        self.move(a, -1, kind=StockMovement.Kind.ADJUSTMENT, on=self.day)
        self.move(b, 4, on=self.day)
        self.move(b, 100, on=self.day + timedelta(days=5))  # out of range
        return a, b

    def test_totals_by_kind_and_overall(self):
        self.seed()
        summary = movement_summary(self.day, self.day, salon=self.salon)
        self.assertEqual(summary.start_date, self.day)
        self.assertEqual(summary.end_date, self.day)
        self.assertEqual(summary.salon_id, self.salon.pk)
        self.assertEqual(summary.movement_count, 4)
        self.assertEqual(summary.total_movements, 4)
        self.assertEqual(summary.net_delta, 10)
        self.assertEqual(summary.net_change, 10)
        self.assertEqual(summary.by_kind, {
            StockMovement.Kind.RECEIVE: 14,
            StockMovement.Kind.SALE: -3,
            StockMovement.Kind.ADJUSTMENT: -1,
            StockMovement.Kind.STOCKTAKE: 0,
        })
        self.assertEqual(summary.by_kind_counts, {
            StockMovement.Kind.RECEIVE: 2,
            StockMovement.Kind.SALE: 1,
            StockMovement.Kind.ADJUSTMENT: 1,
            StockMovement.Kind.STOCKTAKE: 0,
        })
        self.assertEqual(
            totals_by_kind(self.day, self.day, salon=self.salon),
            summary.by_kind,
        )

    def test_totals_by_product_and_net_change(self):
        a, b = self.seed()
        summary = movement_summary(self.day, self.day, salon=self.salon)
        self.assertEqual(
            [row["product_id"] for row in summary.by_product], [a.pk, b.pk]
        )
        alpha, beta = summary.by_product
        self.assertEqual(list(alpha), PRODUCT_FIELDNAMES)
        self.assertEqual(alpha["product_name"], "Alpha")
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
        self.assertEqual(summary.net_by_product, {a.pk: 6, b.pk: 4})
        self.assertEqual(
            totals_by_product(self.day, self.day, salon=self.salon),
            summary.by_product,
        )
        self.assertEqual(
            net_change_by_product(self.day, self.day, salon=self.salon),
            {a.pk: 6, b.pk: 4},
        )
        # Product nets reconcile with the overall net.
        self.assertEqual(
            sum(summary.net_by_product.values()), summary.net_delta
        )

    def test_range_is_inclusive_of_whole_end_day(self):
        p = self.make_product("Shampoo")
        self.move(p, 1, on=self.day - timedelta(days=1))
        self.move(p, 2, on=self.day)
        self.move(p, 3, on=self.day + timedelta(days=1))
        self.move(p, 4, on=self.day + timedelta(days=2))
        summary = movement_summary(
            self.day, self.day + timedelta(days=1), salon=self.salon
        )
        self.assertEqual(summary.movement_count, 2)
        self.assertEqual(summary.net_delta, 5)

    def test_datetime_bounds_reduce_to_local_dates(self):
        p = self.make_product("Shampoo")
        self.move(p, 7, on=self.day)
        start = timezone.make_aware(datetime(2026, 10, 3, 23, 30))
        end = timezone.make_aware(datetime(2026, 10, 3, 1, 0))
        summary = movement_summary(start, end, salon=self.salon)
        self.assertEqual(summary.start_date, self.day)
        self.assertEqual(summary.end_date, self.day)
        self.assertEqual(summary.net_delta, 7)

    def test_salon_scope_is_optional(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        self.move(foreign, 9, on=self.day)
        own = self.make_product("Own")
        self.move(own, 5, on=self.day)
        unscoped = movement_summary(self.day, self.day)
        self.assertIsNone(unscoped.salon_id)
        self.assertEqual(unscoped.movement_count, 2)
        self.assertEqual(unscoped.net_delta, 14)
        scoped = movement_summary(self.day, self.day, salon=self.salon)
        self.assertEqual(scoped.net_by_product, {own.pk: 5})
        by_id = movement_summary(self.day, self.day, salon=other.pk)
        self.assertEqual(by_id.net_by_product, {foreign.pk: 9})

    def test_reversed_range_raises(self):
        with self.assertRaises(ValueError):
            movement_summary(
                self.day + timedelta(days=1), self.day, salon=self.salon
            )
        with self.assertRaises(ValueError):
            totals_by_kind(self.day + timedelta(days=1), self.day)
        with self.assertRaises(ValueError):
            movement_summary(None, self.day)
        with self.assertRaises(ValueError):
            movement_summary("2026-10-03", self.day)

    def test_empty_range_is_zeroed_and_read_only(self):
        p = self.make_product("Shampoo")
        self.move(p, 7, on=self.day)
        empty_day = self.day + timedelta(days=30)
        summary = movement_summary(empty_day, empty_day, salon=self.salon)
        self.assertEqual(summary.movement_count, 0)
        self.assertEqual(summary.net_delta, 0)
        self.assertEqual(summary.by_product, [])
        self.assertEqual(summary.net_by_product, {})
        self.assertTrue(all(v == 0 for v in summary.by_kind.values()))
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(p.current_stock, 7)

    def test_as_dict_is_json_serializable_and_alias(self):
        self.seed()
        summary = stock_movement_summary(self.day, self.day, salon=self.salon)
        payload = summary.as_dict()
        self.assertEqual(json.loads(json.dumps(payload)), payload)
        self.assertEqual(payload["start_date"], "2026-10-03")
        self.assertEqual(payload["net_delta"], 10)
