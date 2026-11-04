"""Tests for the export_movement management command.

The command is a thin wrapper around
``catalog.movement_export.export_movement_export``; these tests
check delegation (stdout/file match the service output verbatim,
as JSON by default and as CSV with ``--format csv``), salon
scoping, date filtering, and clean failure for an unknown salon,
an invalid format, an invalid range bound, and an unwritable
output.
"""
import csv
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
from catalog.movement_export import (
    MOVEMENT_FIELDNAMES,
    export_movement_export,
    export_movements_csv,
)
from saloncore.models import Salon


class ExportMovementCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.day = date(2026, 10, 3)
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        self.move(self.product, 10, note="delivery", on=self.day)
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
        return json.dumps(
            export_movement_export(*args, **kwargs), indent=2) + "\n"

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_movement", salon_id=self.salon.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, self.expected_text(self.salon))
        data = json.loads(text)
        self.assertEqual([m["product_name"] for m in data["movements"]],
                         ["Shampoo", "Shampoo"])
        self.assertEqual(data["totals"][0]["net_delta"], 7)
        self.assertNotIn("Foreign", text)

    def test_date_range_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_movement", "--salon-id", str(self.salon.pk),
            "--start-date", self.day.isoformat(),
            "--end-date", self.day.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            self.expected_text(self.salon, start=self.day, end=self.day))
        after = self.day + timedelta(days=1)
        out = io.StringIO()
        call_command("export_movement", salon_id=self.salon.pk,
                     start_date=after, stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         {"movements": [], "totals": []})

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "movement.json")
            call_command("export_movement", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self.expected_text(self.salon))
        self.assertEqual(out.getvalue(), "")

    def expected_csv(self, *args, **kwargs):
        return export_movements_csv(*args, **kwargs)

    def test_default_format_remains_json(self):
        out = io.StringIO()
        call_command("export_movement", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), self.expected_text(self.salon))

    def test_explicit_json_format_matches_service(self):
        out = io.StringIO()
        call_command("export_movement", salon_id=self.salon.pk,
                     format="json", stdout=out)
        self.assertEqual(out.getvalue(), self.expected_text(self.salon))

    def test_csv_format_matches_service(self):
        out = io.StringIO()
        call_command("export_movement", salon_id=self.salon.pk,
                     format="csv", stdout=out)
        self.assertEqual(out.getvalue(), self.expected_csv(self.salon))
        self.assertNotIn("Foreign", out.getvalue())

    def test_csv_flag_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_movement", "--salon-id", str(self.salon.pk),
            "--start-date", self.day.isoformat(),
            "--end-date", self.day.isoformat(),
            "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            self.expected_csv(self.salon, start=self.day, end=self.day))

    def test_csv_content_equals_json_rows(self):
        out = io.StringIO()
        call_command("export_movement", salon_id=self.salon.pk,
                     format="csv", stdout=out)
        text = out.getvalue()
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], MOVEMENT_FIELDNAMES)
        rows = json.loads(self.expected_text(self.salon))["movements"]
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            parsed, [{k: str(v) for k, v in r.items()} for r in rows])
        self.assertEqual(len(lines), len(rows) + 1)

    def test_csv_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "movement.csv")
            call_command("export_movement", salon_id=self.salon.pk,
                         format="csv", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self.expected_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_movement", salon_id=self.salon.pk,
                         format="xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_movement", salon_id=999999,
                         stdout=io.StringIO())

    def test_invalid_bound_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_movement", salon_id=self.salon.pk,
                         start_date="not-a-date", stdout=io.StringIO())

    def make_conditioner(self):
        conditioner = Product.objects.create(
            salon=self.salon, name="Conditioner", sku="CO-002",
            barcode="222", price=Decimal("12.00"))
        self.move(conditioner, 6, on=self.day)
        return conditioner

    def test_product_id_flag_scopes_json_to_that_product(self):
        conditioner = self.make_conditioner()
        out = io.StringIO()
        call_command(
            "export_movement", "--salon-id", str(self.salon.pk),
            "--product-id", str(conditioner.pk), stdout=out)
        text = out.getvalue()
        self.assertEqual(
            text, self.expected_text(self.salon, product=conditioner))
        data = json.loads(text)
        self.assertEqual([m["product_name"] for m in data["movements"]],
                         ["Conditioner"])
        self.assertEqual([t["product_id"] for t in data["totals"]],
                         [conditioner.pk])
        self.assertNotIn("Shampoo", text)

    def test_product_id_kwarg_scopes_csv_to_that_product(self):
        conditioner = self.make_conditioner()
        out = io.StringIO()
        call_command("export_movement", salon_id=self.salon.pk,
                     product_id=conditioner.pk, format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            self.expected_csv(self.salon, product=conditioner))
        self.assertNotIn("Shampoo", out.getvalue())

    def test_no_product_flag_is_salon_wide_as_before(self):
        self.make_conditioner()
        out = io.StringIO()
        call_command("export_movement", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), self.expected_text(self.salon))

    def test_unknown_product_id_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_movement", salon_id=self.salon.pk,
                         product_id=999999, stdout=io.StringIO())

    def test_other_salon_product_id_raises_command_error(self):
        foreign = Product.objects.get(salon=self.other, name="Foreign")
        with self.assertRaises(CommandError):
            call_command("export_movement", salon_id=self.salon.pk,
                         product_id=foreign.pk, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "movement.json")
            with self.assertRaises(CommandError):
                call_command("export_movement", salon_id=self.salon.pk,
                             output=path, stdout=io.StringIO())
