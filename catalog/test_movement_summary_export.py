"""Tests for the movement summary CSV export service.

The export is a thin rendering of
``catalog.movement_summary.movement_summary``; these tests check
delegation (rows/CSV match the service's ``by_product`` rows),
salon scoping, range validation, the JSON rendering of ``by_kind``
in CSV, and the empty-range header-only case.
"""
import csv
import io
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from catalog.models import Product, StockMovement
from catalog.movement_summary import movement_summary
from catalog.movement_summary_export import (
    MOVEMENT_SUMMARY_FIELDNAMES,
    export_movement_summary,
    export_movement_summary_csv,
)
from saloncore.models import Salon


class MovementSummaryExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
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
        return movement

    def seed(self):
        a = self.make_product("Alpha", sku="A-1", barcode="111")
        b = self.make_product("Beta", sku="B-1", barcode="222")
        self.move(a, 10, on=self.day)
        self.move(a, -3, kind=StockMovement.Kind.SALE, on=self.day)
        self.move(b, 4, on=self.day)
        self.move(b, 100, on=self.day + timedelta(days=5))
        foreign = self.make_product("Foreign", salon=self.other)
        self.move(foreign, 9, on=self.day)
        return a, b

    def test_fieldnames_and_header(self):
        self.assertEqual(
            MOVEMENT_SUMMARY_FIELDNAMES,
            ["product_id", "product_name", "sku", "barcode",
             "movement_count", "net_delta", "by_kind"],
        )
        text = export_movement_summary_csv(
            self.day, self.day, salon=self.salon)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], MOVEMENT_SUMMARY_FIELDNAMES)

    def test_rows_match_service(self):
        a, b = self.seed()
        records = export_movement_summary(
            self.day, self.day, salon=self.salon)
        summary = movement_summary(self.day, self.day, salon=self.salon)
        self.assertEqual(records, summary.by_product)
        self.assertEqual(
            [r["product_id"] for r in records], [a.pk, b.pk])
        self.assertEqual(records[0]["net_delta"], 7)
        self.assertEqual(records[0]["by_kind"], {
            StockMovement.Kind.RECEIVE: 10,
            StockMovement.Kind.SALE: -3,
        })
        self.assertEqual(json.loads(json.dumps(records)), records)
        self.assertNotIn("Foreign", [r["product_name"] for r in records])

    def test_csv_rows_match_dict_export(self):
        self.seed()
        records = export_movement_summary(
            self.day, self.day, salon=self.salon)
        parsed = list(csv.DictReader(io.StringIO(
            export_movement_summary_csv(
                self.day, self.day, salon=self.salon))))
        self.assertEqual(len(parsed), len(records))
        for row, record in zip(parsed, records):
            self.assertEqual(int(row["product_id"]), record["product_id"])
            self.assertEqual(row["product_name"], record["product_name"])
            self.assertEqual(
                int(row["movement_count"]), record["movement_count"])
            self.assertEqual(int(row["net_delta"]), record["net_delta"])
            self.assertEqual(json.loads(row["by_kind"]), {
                k: v for k, v in record["by_kind"].items()
            })

    def test_empty_range_is_header_only(self):
        self.seed()
        later = self.day + timedelta(days=30)
        self.assertEqual(
            export_movement_summary(later, later, salon=self.salon), [])
        self.assertEqual(
            export_movement_summary_csv(later, later, salon=self.salon),
            ",".join(MOVEMENT_SUMMARY_FIELDNAMES) + "\n",
        )

    def test_reversed_and_missing_bounds_raise(self):
        with self.assertRaises(ValueError):
            export_movement_summary(
                self.day + timedelta(days=1), self.day, salon=self.salon)
        with self.assertRaises(ValueError):
            export_movement_summary_csv(None, self.day, salon=self.salon)

    def test_read_only(self):
        self.seed()
        before = StockMovement.objects.count()
        export_movement_summary_csv(self.day, self.day, salon=self.salon)
        self.assertEqual(StockMovement.objects.count(), before)
        self.assertEqual(Product.objects.count(), 3)
