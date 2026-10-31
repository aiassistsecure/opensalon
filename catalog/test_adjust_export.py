import csv
import io
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from catalog.adjust import adjust_stock
from catalog.adjust_export import (
    ADJUST_FIELDNAMES,
    export_stock_adjustments,
    export_stock_adjustments_csv,
    stock_adjustments_csv,
)
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class StockAdjustmentExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.day = date(2026, 10, 3)

    def make_product(self, name, sku="", barcode="", salon=None):
        return Product.objects.create(
            salon=salon or self.salon, name=name, sku=sku,
            barcode=barcode, price=Decimal("10.00"),
        )

    def move(self, product, delta, kind=StockMovement.Kind.ADJUSTMENT,
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

    def test_csv_header(self):
        text = export_stock_adjustments_csv(self.salon)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], ADJUST_FIELDNAMES)
        self.assertEqual(
            ADJUST_FIELDNAMES,
            ["id", "product_id", "product_name", "sku", "barcode",
             "quantity_delta", "note", "created_at"],
        )

    def test_rows_carry_only_adjustment_fields(self):
        p = self.make_product("Shampoo", sku="SH-001", barcode="0123")
        m = self.move(p, -2, note="Damaged bottles", on=self.day)
        (record,) = export_stock_adjustments(self.salon, self.day, self.day)
        self.assertEqual(list(record), ADJUST_FIELDNAMES)
        self.assertEqual(record["id"], m.pk)
        self.assertEqual(record["product_id"], p.pk)
        self.assertEqual(record["product_name"], "Shampoo")
        self.assertEqual(record["sku"], "SH-001")
        self.assertEqual(record["barcode"], "0123")
        self.assertEqual(record["quantity_delta"], -2)
        self.assertEqual(record["note"], "Damaged bottles")
        self.assertEqual(record["created_at"], m.created_at.isoformat())
        self.assertEqual(json.loads(json.dumps(record)), record)
        parsed = list(csv.DictReader(io.StringIO(
            export_stock_adjustments_csv(self.salon, self.day, self.day))))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["id"], str(m.pk))
        self.assertEqual(parsed[0]["quantity_delta"], "-2")
        self.assertEqual(parsed[0]["note"], "Damaged bottles")

    def test_only_adjustments_included(self):
        p = self.make_product("Shampoo")
        self.move(p, 10, kind=StockMovement.Kind.RECEIVE, on=self.day)
        self.move(p, -1, kind=StockMovement.Kind.SALE, on=self.day)
        self.move(p, 5, kind=StockMovement.Kind.STOCKTAKE, on=self.day)
        adj = self.move(p, -2, note="Recount", on=self.day)
        rows = export_stock_adjustments(self.salon, self.day, self.day)
        self.assertEqual([r["id"] for r in rows], [adj.pk])

    def test_adjustments_via_service_are_exported(self):
        p = self.make_product("Shampoo")
        StockMovement.objects.create(
            product=p, kind=StockMovement.Kind.RECEIVE, quantity_delta=10)
        adjust_stock(p, -3, "Damaged bottles")
        rows = export_stock_adjustments(self.salon)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["quantity_delta"], -3)
        self.assertEqual(rows[0]["note"], "Damaged bottles")

    def test_empty_range_is_header_only_and_empty_list(self):
        p = self.make_product("Shampoo")
        self.move(p, 3, note="Recount", on=self.day)
        empty_day = self.day + timedelta(days=30)
        self.assertEqual(
            export_stock_adjustments(self.salon, empty_day, empty_day), [])
        self.assertEqual(
            export_stock_adjustments_csv(self.salon, empty_day, empty_day),
            ",".join(ADJUST_FIELDNAMES) + "\n",
        )
        # Salon with no adjustments at all: also header only.
        fresh = Salon.objects.create(name="Fresh Salon")
        self.assertEqual(
            export_stock_adjustments_csv(fresh),
            ",".join(ADJUST_FIELDNAMES) + "\n",
        )

    def test_range_boundaries_inclusive(self):
        p = self.make_product("Shampoo")
        before = self.move(p, 1, on=self.day - timedelta(days=1))
        first = self.move(p, 2, on=self.day)
        last = self.move(p, 3, on=self.day + timedelta(days=1))
        after = self.move(p, 4, on=self.day + timedelta(days=2))
        rows = export_stock_adjustments(
            self.salon, self.day, self.day + timedelta(days=1))
        self.assertEqual([r["id"] for r in rows], [first.pk, last.pk])
        self.assertNotIn(before.pk, [r["id"] for r in rows])
        self.assertNotIn(after.pk, [r["id"] for r in rows])
        # Single-day range includes that whole day.
        single = export_stock_adjustments(self.salon, self.day, self.day)
        self.assertEqual([r["id"] for r in single], [first.pk])

    def test_salon_scoping_no_leak(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        self.move(foreign, 9, note="Foreign recount", on=self.day)
        own = self.make_product("Own")
        mine = self.move(own, 5, note="Recount", on=self.day)
        rows = export_stock_adjustments(self.salon, self.day, self.day)
        self.assertEqual([r["id"] for r in rows], [mine.pk])
        parsed = list(csv.DictReader(io.StringIO(
            export_stock_adjustments_csv(self.salon))))
        self.assertEqual([r["product_name"] for r in parsed], ["Own"])

    def test_ordering_by_created_at_then_id(self):
        p = self.make_product("Shampoo")
        later = self.move(p, 1, note="later", on=self.day + timedelta(days=1))
        earlier = self.move(p, 2, note="earlier", on=self.day)
        same_day_second = self.move(p, 3, note="same day", on=self.day)
        rows = export_stock_adjustments(self.salon)
        self.assertEqual(
            [r["id"] for r in rows],
            [earlier.pk, same_day_second.pk, later.pk],
        )

    def test_alias_matches_and_read_only(self):
        p = self.make_product("Shampoo")
        self.move(p, 4, note="Recount", on=self.day)
        self.assertEqual(
            stock_adjustments_csv(self.salon),
            export_stock_adjustments_csv(self.salon),
        )
        before = StockMovement.objects.count()
        export_stock_adjustments_csv(self.salon)
        export_stock_adjustments(self.salon)
        self.assertEqual(StockMovement.objects.count(), before)
        self.assertEqual(Product.objects.count(), 1)
