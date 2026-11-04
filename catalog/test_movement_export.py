import csv
import io
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
    export_movements_csv,
    movement_totals,
    movements_csv,
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

    def test_csv_header_and_rows_equal_list_export(self):
        p = self.make_product("Shampoo", sku="SH-001", barcode="0123")
        self.move(p, 10, note="delivery", on=self.day)
        self.move(p, -3, kind=StockMovement.Kind.SALE, on=self.day)
        text = export_movements_csv(self.salon, self.day, self.day)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], MOVEMENT_FIELDNAMES)
        records = export_movements(self.salon, self.day, self.day)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            parsed,
            [{k: str(v) for k, v in r.items()} for r in records])
        self.assertEqual([list(r) for r in parsed],
                         [MOVEMENT_FIELDNAMES] * len(records))
        self.assertIs(movements_csv, export_movements_csv)

    def test_csv_empty_range_is_header_only(self):
        p = self.make_product("Shampoo")
        self.move(p, 7, on=self.day)
        empty_day = self.day + timedelta(days=30)
        self.assertEqual(
            export_movements_csv(self.salon, empty_day, empty_day),
            ",".join(MOVEMENT_FIELDNAMES) + "\n")

    def test_combined_export_and_read_only(self):
        p = self.make_product("Shampoo")
        self.move(p, 5, on=self.day)
        combined = export_movement_export(self.salon, self.day, self.day)
        self.assertEqual(len(combined["movements"]), 1)
        self.assertEqual(combined["totals"][0]["net_delta"], 5)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(p.current_stock, 5)


class MovementExportProductFilterTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.day = date(2026, 10, 3)
        self.alpha = Product.objects.create(
            salon=self.salon, name="Alpha", sku="A-1",
            price=Decimal("10.00"))
        self.beta = Product.objects.create(
            salon=self.salon, name="Beta", sku="B-1",
            price=Decimal("10.00"))
        self.foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="F-1",
            price=Decimal("10.00"))

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE,
             note="", on=None):
        movement = StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta, note=note)
        if on is not None:
            moment = timezone.make_aware(
                datetime(on.year, on.month, on.day, 12, 0))
            StockMovement.objects.filter(pk=movement.pk).update(
                created_at=moment)
            movement.created_at = moment
        return movement

    def seed(self):
        self.move(self.alpha, 10, on=self.day)
        self.move(self.alpha, -3, kind=StockMovement.Kind.SALE,
                  on=self.day)
        self.move(self.beta, 4, on=self.day)
        self.move(self.foreign, 9, on=self.day)

    def test_filtered_contains_only_that_product(self):
        self.seed()
        for product in (self.alpha, self.alpha.pk):
            rows = export_movements(
                self.salon, self.day, self.day, product=product)
            self.assertEqual([r["product_id"] for r in rows],
                             [self.alpha.pk, self.alpha.pk])
            self.assertEqual([r["quantity_delta"] for r in rows], [10, -3])

    def test_filtered_still_applies_date_window(self):
        self.seed()
        self.move(self.alpha, 100, on=self.day + timedelta(days=5))
        rows = export_movements(
            self.salon, self.day, self.day, product=self.alpha)
        self.assertEqual([r["quantity_delta"] for r in rows], [10, -3])
        rows = export_movements(self.salon, product=self.alpha)
        self.assertEqual([r["quantity_delta"] for r in rows],
                         [10, -3, 100])

    def test_unfiltered_output_unchanged(self):
        self.seed()
        plain = export_movements(self.salon, self.day, self.day)
        self.assertEqual(
            export_movements(self.salon, self.day, self.day, product=None),
            plain)
        self.assertEqual(
            [r["product_id"] for r in plain],
            [self.alpha.pk, self.alpha.pk, self.beta.pk])
        self.assertEqual(
            export_movements_csv(self.salon, self.day, self.day,
                                 product=None),
            export_movements_csv(self.salon, self.day, self.day))

    def test_filtered_csv_matches_filtered_list(self):
        self.seed()
        text = export_movements_csv(
            self.salon, self.day, self.day, product=self.beta)
        parsed = list(csv.DictReader(io.StringIO(text)))
        records = export_movements(
            self.salon, self.day, self.day, product=self.beta)
        self.assertEqual(
            parsed,
            [{k: str(v) for k, v in r.items()} for r in records])
        self.assertEqual([r["product_id"] for r in parsed],
                         [str(self.beta.pk)])

    def test_filtered_totals_reconcile_with_filtered_rows(self):
        self.seed()
        combined = export_movement_export(
            self.salon, self.day, self.day, product=self.alpha)
        self.assertEqual(
            [t["product_id"] for t in combined["totals"]], [self.alpha.pk])
        self.assertEqual(combined["totals"][0]["movement_count"], 2)
        self.assertEqual(combined["totals"][0]["net_delta"], 7)
        self.assertEqual(
            sum(t["net_delta"] for t in combined["totals"]),
            sum(r["quantity_delta"] for r in combined["movements"]))

    def test_product_with_no_movements_exports_empty(self):
        self.seed()
        empty = Product.objects.create(
            salon=self.salon, name="Empty", price=Decimal("1.00"))
        self.assertEqual(
            export_movements(self.salon, product=empty), [])

    def test_unknown_product_id_raises_value_error(self):
        self.seed()
        with self.assertRaises(ValueError):
            export_movements(self.salon, product=999999)
        with self.assertRaises(ValueError):
            export_movements_csv(self.salon, product=999999)

    def test_other_salon_product_raises_value_error(self):
        self.seed()
        for product in (self.foreign, self.foreign.pk):
            with self.assertRaises(ValueError):
                export_movements(self.salon, product=product)


class MovementExportKindFilterTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.day = date(2026, 10, 3)
        self.alpha = Product.objects.create(
            salon=self.salon, name="Alpha", sku="A-1",
            price=Decimal("10.00"))
        self.beta = Product.objects.create(
            salon=self.salon, name="Beta", sku="B-1",
            price=Decimal("10.00"))

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE,
             note="", on=None):
        movement = StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta, note=note)
        if on is not None:
            moment = timezone.make_aware(
                datetime(on.year, on.month, on.day, 12, 0))
            StockMovement.objects.filter(pk=movement.pk).update(
                created_at=moment)
            movement.created_at = moment
        return movement

    def seed(self):
        self.move(self.alpha, 10, on=self.day)
        self.move(self.alpha, -3, kind=StockMovement.Kind.SALE,
                  on=self.day)
        self.move(self.alpha, -2, kind=StockMovement.Kind.ADJUSTMENT,
                  on=self.day)
        self.move(self.beta, -4, kind=StockMovement.Kind.SALE,
                  on=self.day)

    def test_kind_filter_dict_and_csv(self):
        self.seed()
        records = export_movements(self.salon, kind="sale")
        self.assertEqual(
            [r["quantity_delta"] for r in records], [-3, -4])
        self.assertEqual([r["kind"] for r in records], ["sale", "sale"])
        parsed = list(csv.DictReader(io.StringIO(
            export_movements_csv(self.salon, kind="sale"))))
        self.assertEqual(
            parsed,
            [{k: str(v) for k, v in r.items()} for r in records])

    def test_kind_filter_accepts_enum_and_defaults_identical(self):
        self.seed()
        self.assertEqual(
            export_movements(
                self.salon, kind=StockMovement.Kind.SALE),
            export_movements(self.salon, kind="sale"))
        self.assertEqual(
            export_movements(self.salon),
            export_movements(self.salon, kind=None))
        self.assertEqual(
            export_movements_csv(self.salon),
            export_movements_csv(self.salon, kind=None))
        self.assertEqual(
            export_movement_export(self.salon),
            export_movement_export(self.salon, kind=None))

    def test_kind_filter_exact_no_case_folding_and_no_match(self):
        self.seed()
        self.assertEqual(export_movements(self.salon, kind="SALE"), [])
        self.assertEqual(export_movements(self.salon, kind="Sale"), [])
        self.assertEqual(
            export_movements(self.salon, kind="stocktake"), [])
        self.assertEqual(
            export_movements_csv(self.salon, kind="SALE"),
            ",".join(MOVEMENT_FIELDNAMES) + "\n")

    def test_kind_filter_composes_with_window_and_product(self):
        self.seed()
        self.move(self.alpha, -9, kind=StockMovement.Kind.SALE,
                  on=self.day + timedelta(days=5))
        records = export_movements(
            self.salon, self.day, self.day, product=self.alpha,
            kind="sale")
        self.assertEqual([r["quantity_delta"] for r in records], [-3])
        self.assertEqual(
            [r["quantity_delta"] for r in export_movements(
                self.salon, product=self.beta, kind="sale")],
            [-4])
        self.assertEqual(
            export_movements(
                self.salon, self.day, self.day, kind="receive",
                product=self.beta),
            [])

    def test_kind_filtered_totals_reconcile_with_rows(self):
        self.seed()
        combined = export_movement_export(self.salon, kind="sale")
        self.assertEqual(
            [t["product_id"] for t in combined["totals"]],
            [self.alpha.pk, self.beta.pk])
        alpha = combined["totals"][0]
        self.assertEqual(alpha["movement_count"], 1)
        self.assertEqual(alpha["net_delta"], -3)
        self.assertEqual(alpha["by_kind"], {"sale": -3})
        self.assertEqual(
            sum(t["net_delta"] for t in combined["totals"]),
            sum(r["quantity_delta"] for r in combined["movements"]))
        self.assertEqual(
            movement_totals(self.salon, kind="receive")[0]["by_kind"],
            {"receive": 10})
