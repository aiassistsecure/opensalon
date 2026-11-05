"""Tests for the export_movement_summary management command.

The command is a thin wrapper around
``catalog.movement_summary_export.export_movement_summary_csv``;
these tests check delegation (stdout/file match the service
output verbatim), salon scoping, and clean failure for an unknown
salon, an invalid or reversed range, and an unwritable output.
"""
import io
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from catalog.models import Product, StockMovement
from catalog.movement_summary_export import (
    export_movement_summary,
    export_movement_summary_csv,
)
from saloncore.models import Salon


class ExportMovementSummaryCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.day = date(2026, 10, 3)
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        self.move(self.product, 10, on=self.day)
        self.move(self.product, -3, kind=StockMovement.Kind.SALE,
                  on=self.day)
        foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))
        self.move(foreign, 9, on=self.day)

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE,
             note="", on=None):
        movement = StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta, note=note)
        if on is not None:
            moment = timezone.make_aware(
                datetime(on.year, on.month, on.day, 12, 0))
            StockMovement.objects.filter(pk=movement.pk).update(
                created_at=moment)
        return movement

    def expected_text(self, *args, **kwargs):
        return export_movement_summary_csv(*args, **kwargs)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_movement_summary", salon_id=self.salon.pk,
            start_date=self.day, end_date=self.day, stdout=out)
        text = out.getvalue()
        self.assertEqual(
            text, self.expected_text(self.day, self.day, salon=self.salon))
        self.assertIn("Shampoo", text)
        self.assertNotIn("Foreign", text)

    def test_cli_date_strings_match_service(self):
        out = io.StringIO()
        call_command(
            "export_movement_summary", "--salon-id", str(self.salon.pk),
            "--start-date", self.day.isoformat(),
            "--end-date", self.day.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            self.expected_text(self.day, self.day, salon=self.salon))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "summary.csv")
            call_command(
                "export_movement_summary", salon_id=self.salon.pk,
                start_date=self.day, end_date=self.day,
                output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(
            text, self.expected_text(self.day, self.day, salon=self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_movement_summary", salon_id=999999,
                start_date=self.day, end_date=self.day,
                stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_movement_summary", salon_id=self.salon.pk,
                start_date="not-a-date", end_date=self.day,
                stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_movement_summary", salon_id=self.salon.pk,
                start_date=self.day + timedelta(days=1),
                end_date=self.day, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "summary.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_movement_summary", salon_id=self.salon.pk,
                    start_date=self.day, end_date=self.day,
                    output=path, stdout=io.StringIO())


class ExportMovementSummaryFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.empty = Salon.objects.create(name="Empty Salon")
        self.day = date(2026, 10, 3)
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        self.move(self.product, 10, on=self.day)
        self.move(self.product, -3, kind=StockMovement.Kind.SALE,
                  on=self.day)
        # A movement well after the single-day window used below.
        self.move(self.product, 100,
                  on=self.day + timedelta(days=5))

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE,
             note="", on=None):
        movement = StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta, note=note)
        if on is not None:
            moment = timezone.make_aware(
                datetime(on.year, on.month, on.day, 12, 0))
            StockMovement.objects.filter(pk=movement.pk).update(
                created_at=moment)
        return movement

    def rows(self, *args, **kwargs):
        return export_movement_summary(*args, **kwargs)

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command(
            "export_movement_summary", salon_id=self.salon.pk,
            start_date=self.day, end_date=self.day, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_movement_summary_csv(
                self.day, self.day, salon=self.salon))

    def test_explicit_csv_format_kwargs_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_movement_summary", salon_id=self.salon.pk,
            start_date=self.day, end_date=self.day,
            format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_movement_summary_csv(
                self.day, self.day, salon=self.salon))

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command(
            "export_movement_summary", "--salon-id", str(self.salon.pk),
            "--start-date", self.day.isoformat(),
            "--end-date", self.day.isoformat(),
            "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_movement_summary_csv(
                self.day, self.day, salon=self.salon))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command(
            "export_movement_summary", salon_id=self.salon.pk,
            start_date=self.day, end_date=self.day,
            format="json", stdout=out)
        rows = self.rows(self.day, self.day, salon=self.salon)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(out.getvalue(), json.dumps(rows, indent=2) + "\n")

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(
            "export_movement_summary", "--salon-id", str(self.salon.pk),
            "--start-date", self.day.isoformat(),
            "--end-date", self.day.isoformat(),
            "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            self.rows(self.day, self.day, salon=self.salon))

    def test_json_empty_range_is_empty_list(self):
        later = self.day + timedelta(days=30)
        out = io.StringIO()
        call_command(
            "export_movement_summary", salon_id=self.empty.pk,
            start_date=later, end_date=later,
            format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(
            json.loads(out.getvalue()),
            self.rows(later, later, salon=self.empty))
        self.assertEqual(out.getvalue(), "[]\n")

    def test_json_composes_with_date_window(self):
        out = io.StringIO()
        call_command(
            "export_movement_summary", salon_id=self.salon.pk,
            start_date=self.day, end_date=self.day,
            format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(
            rows, self.rows(self.day, self.day, salon=self.salon))
        self.assertEqual(rows[0]["movement_count"], 2)
        self.assertEqual(rows[0]["net_delta"], 7)

    def test_csv_composes_with_date_window(self):
        out = io.StringIO()
        call_command(
            "export_movement_summary", salon_id=self.salon.pk,
            start_date=self.day, end_date=self.day,
            format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_movement_summary_csv(
                self.day, self.day, salon=self.salon))

    def test_json_output_file_parses_and_equals_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "summary.json")
            call_command(
                "export_movement_summary", salon_id=self.salon.pk,
                start_date=self.day, end_date=self.day,
                format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        rows = self.rows(self.day, self.day, salon=self.salon)
        self.assertEqual(json.loads(text), rows)
        self.assertEqual(text, json.dumps(rows, indent=2) + "\n")
        self.assertEqual(out.getvalue(), "")

    def test_json_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_movement_summary", salon_id=self.salon.pk,
                start_date=self.day + timedelta(days=1),
                end_date=self.day, format="json",
                stdout=io.StringIO())

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_movement_summary", salon_id=self.salon.pk,
                start_date=self.day, end_date=self.day,
                format="xml", stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(
                "export_movement_summary", "--salon-id",
                str(self.salon.pk), "--start-date", self.day.isoformat(),
                "--end-date", self.day.isoformat(),
                "--format", "xml", stdout=io.StringIO())
