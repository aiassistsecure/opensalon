import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from catalog.history import stock_history
from catalog.history_export import (
    HISTORY_FIELDNAMES,
    export_stock_history,
    export_stock_history_csv,
    history_csv,
    stock_history_csv,
)
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class StockHistoryExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, sku="", barcode="", salon=None):
        return Product.objects.create(
            salon=salon or self.salon, name=name, sku=sku,
            barcode=barcode, price=Decimal("24.00"),
        )

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE,
             note=""):
        return StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta, note=note
        )

    def test_csv_header_and_fieldnames(self):
        product = self.make_product("Shampoo")
        self.move(product, 5)
        rows = list(csv.reader(io.StringIO(
            export_stock_history_csv(self.salon, product))))
        self.assertEqual(rows[0], HISTORY_FIELDNAMES)
        self.assertEqual(
            HISTORY_FIELDNAMES,
            ["id", "product_id", "product_name", "sku", "barcode",
             "kind", "quantity_delta", "note", "running_balance",
             "created_at"],
        )

    def test_rows_match_service_output(self):
        product = self.make_product(
            "Shampoo", sku="SH-001", barcode="012345678905")
        self.move(product, 10, note="delivery")
        self.move(product, -3, kind=StockMovement.Kind.SALE)
        self.move(product, -2, kind=StockMovement.Kind.ADJUSTMENT,
                  note="damaged")

        history = stock_history(self.salon, product)
        records = export_stock_history(self.salon, product)
        self.assertEqual(len(records), len(history.entries))
        for record, entry in zip(records, history.entries):
            self.assertEqual(list(record.keys()), HISTORY_FIELDNAMES)
            self.assertEqual(record["id"], entry.movement.pk)
            self.assertEqual(record["product_id"], product.pk)
            self.assertEqual(record["product_name"], product.name)
            self.assertEqual(record["sku"], product.sku)
            self.assertEqual(record["barcode"], product.barcode)
            self.assertEqual(record["kind"], entry.kind)
            self.assertEqual(record["quantity_delta"],
                             entry.quantity_delta)
            self.assertEqual(record["note"], entry.note)
            self.assertEqual(record["running_balance"],
                             entry.running_balance)
            self.assertEqual(record["created_at"],
                             entry.created_at.isoformat())
        self.assertEqual(
            [r["running_balance"] for r in records], [10, 7, 5])
        self.assertEqual(records[-1]["running_balance"],
                         history.final_balance)
        # JSON-serializable, and the CSV export agrees row for row.
        self.assertEqual(json.loads(json.dumps(records)), records)
        parsed = list(csv.DictReader(io.StringIO(
            export_stock_history_csv(self.salon, product))))
        self.assertEqual(
            [int(r["id"]) for r in parsed], [r["id"] for r in records])
        self.assertEqual(
            [r["running_balance"] for r in parsed],
            [str(r["running_balance"]) for r in records],
        )

    def test_only_this_products_movements_are_included(self):
        product = self.make_product("Own")
        other_product = self.make_product("Other Product")
        self.move(product, 4)
        self.move(other_product, 99)
        records = export_stock_history(self.salon, product)
        self.assertEqual([r["quantity_delta"] for r in records], [4])

    def test_salon_isolation_and_invalid_product_raise(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        self.move(foreign, 6)
        with self.assertRaises(ValueError):
            export_stock_history(self.salon, foreign)
        with self.assertRaises(ValueError):
            export_stock_history_csv(self.salon, foreign.pk)
        with self.assertRaises(ValueError):
            export_stock_history(self.salon, 999999)
        # Its own salon exports it fine, by instance and by id.
        self.assertEqual(
            export_stock_history(other, foreign)[0]["running_balance"],
            6)
        self.assertEqual(
            export_stock_history(other, foreign.pk)[0]["product_name"],
            "Foreign")

    def test_product_with_no_movements_is_header_only(self):
        product = self.make_product("Never Stocked")
        self.assertEqual(export_stock_history(self.salon, product), [])
        self.assertEqual(
            export_stock_history_csv(self.salon, product),
            ",".join(HISTORY_FIELDNAMES) + "\n",
        )

    def move_on(self, product, delta, on, kind=StockMovement.Kind.RECEIVE,
                note=""):
        movement = self.move(product, delta, kind=kind, note=note)
        moment = timezone.make_aware(
            datetime(on.year, on.month, on.day, 12, 0))
        StockMovement.objects.filter(pk=movement.pk).update(
            created_at=moment)
        movement.created_at = moment
        return movement

    def test_window_filters_on_created_at_whole_days(self):
        product = self.make_product("Shampoo")
        day1, day2, day3 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)
        self.move_on(product, 10, day1)
        self.move_on(product, -3, day2, kind=StockMovement.Kind.SALE)
        self.move_on(product, -2, day3, kind=StockMovement.Kind.ADJUSTMENT)

        records = export_stock_history(
            self.salon, product, start=day2, end=day3)
        self.assertEqual([r["quantity_delta"] for r in records], [-3, -2])
        # running_balance is the full-ledger balance, not recomputed
        # over the window.
        self.assertEqual([r["running_balance"] for r in records], [7, 5])
        # Start-only and end-only bounds.
        self.assertEqual(
            [r["quantity_delta"] for r in export_stock_history(
                self.salon, product, start=day2)],
            [-3, -2])
        self.assertEqual(
            [r["quantity_delta"] for r in export_stock_history(
                self.salon, product, end=day1)],
            [10])
        # A window covering nothing exports empty / header only.
        self.assertEqual(
            export_stock_history(self.salon, product, start=date(2027, 1, 1)),
            [])
        self.assertEqual(
            export_stock_history_csv(
                self.salon, product, start=date(2027, 1, 1)),
            ",".join(HISTORY_FIELDNAMES) + "\n")
        # CSV twin agrees with the list export under the same window.
        parsed = list(csv.DictReader(io.StringIO(export_stock_history_csv(
            self.salon, product, start=day2, end=day3))))
        self.assertEqual(
            [int(r["id"]) for r in parsed], [r["id"] for r in records])

    def test_window_default_is_byte_identical_and_composes_with_product(self):
        product = self.make_product("Shampoo")
        other = self.make_product("Other")
        day = date(2026, 2, 10)
        self.move_on(product, 4, day)
        self.move_on(other, 99, day)
        self.assertEqual(
            export_stock_history(self.salon, product),
            export_stock_history(self.salon, product, start=None, end=None))
        self.assertEqual(
            export_stock_history_csv(self.salon, product),
            export_stock_history_csv(
                self.salon, product, start=None, end=None))
        # Product (by id) AND window both apply.
        records = export_stock_history(
            self.salon, product.pk, start=day, end=day)
        self.assertEqual([r["quantity_delta"] for r in records], [4])
        self.assertEqual(
            export_stock_history(self.salon, product.pk, start=date(2026, 3, 1)),
            [])

    def test_window_datetime_bounds_and_invalid_bound(self):
        product = self.make_product("Shampoo")
        day = date(2026, 3, 15)
        self.move_on(product, 6, day)
        noon = timezone.make_aware(datetime(2026, 3, 15, 12, 0))
        self.assertEqual(
            len(export_stock_history(self.salon, product, start=noon)), 1)
        self.assertEqual(
            export_stock_history(self.salon, product, end=noon), [])
        with self.assertRaises(ValueError):
            export_stock_history(self.salon, product, start="2026-03-15")

    def test_kind_filter_dict_and_csv(self):
        product = self.make_product("Shampoo")
        self.move(product, 10, note="delivery")
        self.move(product, -3, kind=StockMovement.Kind.SALE)
        self.move(product, -2, kind=StockMovement.Kind.ADJUSTMENT,
                  note="damaged")
        records = export_stock_history(self.salon, product, kind="sale")
        self.assertEqual([r["quantity_delta"] for r in records], [-3])
        self.assertEqual(records[0]["kind"], "sale")
        # running_balance is the full-ledger balance, not recomputed
        # over the kind filter.
        self.assertEqual([r["running_balance"] for r in records], [7])
        parsed = list(csv.DictReader(io.StringIO(
            export_stock_history_csv(self.salon, product, kind="sale"))))
        self.assertEqual(
            [(r["kind"], r["quantity_delta"]) for r in parsed],
            [(r["kind"], str(r["quantity_delta"])) for r in records])

    def test_kind_filter_accepts_enum_and_defaults_identical(self):
        product = self.make_product("Shampoo")
        self.move(product, 10)
        self.move(product, -3, kind=StockMovement.Kind.SALE)
        self.assertEqual(
            export_stock_history(
                self.salon, product, kind=StockMovement.Kind.SALE),
            export_stock_history(self.salon, product, kind="sale"))
        self.assertEqual(
            export_stock_history(self.salon, product),
            export_stock_history(self.salon, product, kind=None))
        self.assertEqual(
            export_stock_history_csv(self.salon, product),
            export_stock_history_csv(self.salon, product, kind=None))

    def test_kind_filter_exact_no_case_folding_and_no_match(self):
        product = self.make_product("Shampoo")
        self.move(product, -3, kind=StockMovement.Kind.SALE)
        self.assertEqual(
            export_stock_history(self.salon, product, kind="SALE"), [])
        self.assertEqual(
            export_stock_history(self.salon, product, kind="Sale"), [])
        self.assertEqual(
            export_stock_history(self.salon, product, kind="stocktake"),
            [])
        self.assertEqual(
            export_stock_history_csv(self.salon, product, kind="SALE"),
            ",".join(HISTORY_FIELDNAMES) + "\n")

    def test_kind_filter_composes_with_window_and_product(self):
        product = self.make_product("Shampoo")
        other = self.make_product("Other")
        day1, day2 = date(2026, 1, 5), date(2026, 1, 6)
        self.move_on(product, 10, day1)
        self.move_on(product, -3, day2, kind=StockMovement.Kind.SALE)
        self.move_on(product, -2, day2,
                     kind=StockMovement.Kind.ADJUSTMENT)
        self.move_on(other, -9, day2, kind=StockMovement.Kind.SALE)
        records = export_stock_history(
            self.salon, product, start=day2, end=day2, kind="sale")
        self.assertEqual([r["quantity_delta"] for r in records], [-3])
        self.assertEqual(
            export_stock_history(
                self.salon, product, start=day1, end=day1, kind="sale"),
            [])
        self.assertEqual(
            [r["quantity_delta"] for r in export_stock_history(
                self.salon, other, kind="sale")],
            [-9])

    def test_single_product_argument_and_aliases_read_only(self):
        product = self.make_product("Solo")
        self.move(product, 7)
        before_products = Product.objects.count()
        before_moves = StockMovement.objects.count()
        self.assertEqual(
            export_stock_history(product)[0]["running_balance"], 7)
        self.assertEqual(
            history_csv(self.salon, product),
            export_stock_history_csv(self.salon, product))
        self.assertEqual(
            stock_history_csv(self.salon, product),
            export_stock_history_csv(self.salon, product))
        self.assertEqual(Product.objects.count(), before_products)
        self.assertEqual(StockMovement.objects.count(), before_moves)
