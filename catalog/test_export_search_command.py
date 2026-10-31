"""Tests for the catalog export_search management command.

The command is a thin wrapper around
``catalog.search_export.export_search_products_csv``: these
tests pin that its stdout and file output match that service
verbatim, that query / include_inactive pass through unchanged,
that it scopes to the requested salon, and that unknown salons
and unwritable output fail cleanly as ``CommandError``.

Note: other apps also define an ``export_search`` command, so
these tests load the catalog command class explicitly via
``load_command_class("catalog", "export_search")`` and pass
that instance to ``call_command`` -- pinning this app's
command, not the global name resolution.
"""
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase

from catalog.models import Product
from catalog.search_export import (
    EXPORT_FIELDNAMES,
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
