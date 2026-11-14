"""Tests for the export_salon_data command --format json|csv.

Pins that ``--format json`` (the default) is byte-identical in
shape to the historical export (same top-level keys/sections,
same serialisation), that ``--format csv`` renders the SAME
bundle (section blocks in bundle order, CSV-vs-JSON row parity,
nested dict/list values JSON-encoded into their cell), and
that Payment's ``provider_reference`` is never exported in
either format. Synthetic records only.
"""
import csv
import io
import json
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from checkout.models import Cashup, Payment, Receipt, Sale
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember


def _cell(value):
    """The CSV cell a JSON-bundle value must render as."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=isinstance(value, dict))
    return str(value)


def _blocks(text):
    """Split CSV export text into {section name: block lines}."""
    blocks = {}
    for block in text.rstrip("\n").split("\n\n"):
        lines = block.splitlines()
        assert lines[0].startswith("# section: ")
        blocks[lines[0][len("# section: "):]] = lines[1:]
    return blocks


class ExportSalonDataFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Format Salon", timezone="America/New_York",
            currency="USD")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color", sort_order=1)
        self.payload = {"legacy": {"id": 7, "tags": ["x", "y"]}}
        self.service = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-1", service_minutes=45,
            payload=self.payload)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Ada", last_name="Optin",
            external_id="cli-1", payload=self.payload)
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.sale = Sale.objects.create(
            salon=self.salon, client=self.client,
            status=Sale.Status.COMPLETED)
        Payment.objects.create(
            sale=self.sale, method=Payment.Method.CASH,
            amount=Decimal("85.00"), status=Payment.Status.COMPLETED,
            provider_reference="PROV-SECRET-1")
        start = datetime(2026, 10, 3, 9, 0, tzinfo=dt_timezone.utc)
        Cashup.objects.create(
            salon=self.salon, period_start=start,
            period_end=start + timedelta(hours=8),
            tender_totals={"cash": "85.00"},
            total=Decimal("85.00"))
        Receipt.objects.create(
            sale=self.sale, salon_name="Format Salon",
            lines=[{"description": "Single Process",
                    "unit_price": "85.00"}],
            total=Decimal("85.00"),
            tender=[{"method": "cash", "amount": "85.00"}])

    def run_export(self, suffix=".out", **kwargs):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False, encoding="utf-8")
        fh.close()
        out = io.StringIO()
        call_command("export_salon_data", fh.name, stdout=out, **kwargs)
        with open(fh.name, encoding="utf-8") as exported:
            return exported.read(), out.getvalue()

    def test_default_json_shape_and_serialisation_unchanged(self):
        raw, out = self.run_export()
        self.assertIn("EXPORT_SUMMARY", out)
        data = json.loads(raw)
        # Byte-identical serialisation: indent=2 + trailing newline.
        self.assertEqual(raw, json.dumps(data, indent=2) + "\n")
        # Same top-level keys/sections, in bundle order.
        blocks = _blocks(self.run_export(format="csv")[0])
        self.assertEqual(list(data), list(blocks))
        self.assertEqual(data["counts"]["services"], 1)
        self.assertEqual(data["counts"]["sale_payments"], 1)
        for key, count in data["counts"].items():
            self.assertEqual(len(data[key]), count)

    def test_explicit_json_matches_default_byte_for_byte(self):
        default_raw, _ = self.run_export()
        explicit_raw, _ = self.run_export(format="json")
        self.assertEqual(explicit_raw, default_raw)

    def test_csv_sections_in_bundle_order(self):
        data = json.loads(self.run_export()[0])
        blocks = _blocks(self.run_export(format="csv")[0])
        self.assertEqual(list(blocks), list(data))

    def test_csv_json_row_parity(self):
        data = json.loads(self.run_export()[0])
        blocks = _blocks(self.run_export(format="csv")[0])
        for name, section in data.items():
            rows = [section] if isinstance(section, dict) else section
            lines = blocks[name]
            if not rows:
                self.assertEqual(lines, [])
                continue
            reader = csv.DictReader(io.StringIO("\n".join(lines) + "\n"))
            self.assertEqual(reader.fieldnames, list(rows[0]))
            parsed = list(reader)
            self.assertEqual(len(parsed), len(rows))
            for csv_row, json_row in zip(parsed, rows):
                self.assertEqual(
                    csv_row,
                    {key: _cell(value) for key, value in json_row.items()})

    def test_csv_nested_values_are_json_encoded_cells(self):
        blocks = _blocks(self.run_export(format="csv")[0])
        reader = csv.DictReader(
            io.StringIO("\n".join(blocks["services"]) + "\n"))
        row = next(iter(reader))
        self.assertEqual(json.loads(row["payload"]), self.payload)
        reader = csv.DictReader(
            io.StringIO("\n".join(blocks["cashups"]) + "\n"))
        row = next(iter(reader))
        self.assertEqual(json.loads(row["tender_totals"]),
                         {"cash": "85.00"})
        reader = csv.DictReader(
            io.StringIO("\n".join(blocks["receipts"]) + "\n"))
        row = next(iter(reader))
        self.assertEqual(json.loads(row["lines"]),
                         [{"description": "Single Process",
                           "unit_price": "85.00"}])

    def test_csv_empty_section_is_header_line_alone(self):
        blocks = _blocks(self.run_export(format="csv")[0])
        self.assertEqual(blocks["products"], [])
        self.assertEqual(blocks["refunds"], [])

    def test_provider_reference_never_exported_in_either_format(self):
        for kwargs in ({}, {"format": "json"}, {"format": "csv"}):
            raw, _ = self.run_export(**kwargs)
            self.assertNotIn("provider_reference", raw)
            self.assertNotIn("PROV-SECRET-1", raw)

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            fh = tempfile.NamedTemporaryFile(
                mode="w", suffix=".out", delete=False, encoding="utf-8")
            fh.close()
            call_command("export_salon_data", fh.name,
                         "--format", "xml", stdout=io.StringIO())
