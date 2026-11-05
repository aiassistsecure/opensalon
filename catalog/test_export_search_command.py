"""Tests for the catalog export_search management command.

The command is a thin wrapper around
``catalog.search_export``: these tests pin that its CSV stdout
and file output match ``export_search_products_csv`` verbatim
(byte-identical by default and explicitly), that its JSON
output parses to the dict rows from ``export_search_products``
serialised with ``DjangoJSONEncoder`` and composes with the
query / include_inactive filters, that it scopes to the
requested salon, and that unknown formats, unknown salons and
unwritable output fail cleanly as ``CommandError``.

Note: other apps also define an ``export_search`` command, so
these tests load the catalog command class explicitly via
``load_command_class("catalog", "export_search")`` and pass
that instance to ``call_command`` -- pinning this app's
command, not the global name resolution.
"""
import io
import json
import os
import tempfile
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command, load_command_class
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from catalog.models import Product
from catalog.search_export import (
    EXPORT_FIELDNAMES,
    export_search_products,
    export_search_products_csv,
)
from saloncore.models import Salon


def _cmd():
    return load_command_class("catalog", "export_search")


class ExportSearchCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        Product.objects.create(
            salon=self.salon, name="Lavender Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("24.50"))
        Product.objects.create(
            salon=self.salon, name="Lavender Conditioner", sku="CN-002",
            barcode="012345678906", price=Decimal("19.99"))
        Product.objects.create(
            salon=self.salon, name="Retired Shampoo", sku="SH-999",
            barcode="999", price=Decimal("5.00"), active=False)
        Product.objects.create(
            salon=self.other, name="Lavender Shampoo", sku="FR-999",
            barcode="999999", price=Decimal("1.00"))

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, query="Lavender",
                     stdout=out)
        text = out.getvalue()
        self.assertEqual(
            text,
            export_search_products_csv(self.salon, "Lavender"))
        self.assertEqual(
            text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        self.assertIn("Lavender Shampoo", text)
        self.assertNotIn("FR-999", text)
        self.assertNotIn("Retired Shampoo", text)

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--query", "SH-001", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_search_products_csv(self.salon, "SH-001"))

    def test_include_inactive_matches_service(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, query="Shampoo",
                     include_inactive=True, stdout=out)
        text = out.getvalue()
        self.assertEqual(
            text,
            export_search_products_csv(
                self.salon, "Shampoo", include_inactive=True))
        self.assertIn("Retired Shampoo", text)

    def test_no_query_matches_service(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(
            text, export_search_products_csv(self.salon, None))
        self.assertEqual(text, ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_salon_scoping_matches_service(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.other.pk, query="Lavender",
                     stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_search_products_csv(self.other, "Lavender"))
        self.assertIn("FR-999", out.getvalue())

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "search.csv")
            call_command(_cmd(), salon_id=self.salon.pk,
                         query="Lavender", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(
            text,
            export_search_products_csv(self.salon, "Lavender"))
        self.assertEqual(out.getvalue(), "")

    def test_default_is_csv_byte_identical(self):
        default_out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, query="Lavender",
                     stdout=default_out)
        csv_out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, query="Lavender",
                     format="csv", stdout=csv_out)
        self.assertEqual(default_out.getvalue(), csv_out.getvalue())
        self.assertEqual(
            default_out.getvalue(),
            export_search_products_csv(self.salon, "Lavender"))

    def test_explicit_csv_via_cli_matches_service(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--query", "Lavender", "--format", "csv",
                     stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_search_products_csv(self.salon, "Lavender"))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, query="Lavender",
                     format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_search_products(self.salon, "Lavender"))
        self.assertEqual(
            out.getvalue(),
            json.dumps(
                export_search_products(self.salon, "Lavender"),
                indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_via_cli_matches_dict_service(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--query", "SH-001", "--format", "json",
                     stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_search_products(self.salon, "SH-001"))

    def test_json_composes_with_include_inactive(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, query="Shampoo",
                     include_inactive=True, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(
            rows,
            export_search_products(
                self.salon, "Shampoo", include_inactive=True))
        self.assertIn("Retired Shampoo", [r["name"] for r in rows])

    def test_json_no_query_is_empty_list(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(
            json.loads(out.getvalue()),
            export_search_products(self.salon, None))

    def test_json_scopes_to_salon(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.other.pk, query="Lavender",
                     format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_search_products(self.other, "Lavender"))

    def test_json_delegates_to_dict_service_verbatim(self):
        with mock.patch(
            "catalog.management.commands.export_search"
            ".export_search_products",
            wraps=export_search_products,
        ) as spy:
            call_command(_cmd(), salon_id=self.salon.pk,
                         query="Lavender", format="json",
                         stdout=io.StringIO())
        spy.assert_called_once_with(
            self.salon, "Lavender", include_inactive=False)

    def test_json_output_file_parses_and_equals_dict_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "search.json")
            call_command(_cmd(), salon_id=self.salon.pk,
                         query="Lavender", format="json", output=path,
                         stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written),
            export_search_products(self.salon, "Lavender"))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=self.salon.pk,
                         query="Lavender", format="xml",
                         stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), "--salon-id", str(self.salon.pk),
                         "--query", "Lavender", "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=999999, query="Lavender",
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "search.csv")
            with self.assertRaises(CommandError):
                call_command(_cmd(), salon_id=self.salon.pk,
                             query="Lavender", output=path,
                             stdout=io.StringIO())
