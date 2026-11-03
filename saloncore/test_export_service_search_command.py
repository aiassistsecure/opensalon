"""Tests for the saloncore export_service_search command.

The command is a thin wrapper around
``saloncore.search_export.export_search_services_csv``: these
tests pin that its stdout and file output match that service
verbatim, that query / include_inactive pass through unchanged,
that it scopes to the requested salon, and that unknown salons
and unwritable output fail cleanly as ``CommandError``.
"""
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon, Service, ServiceCategory
from saloncore.search_export import (
    EXPORT_FIELDNAMES,
    export_search_services_csv,
)


class ExportServiceSearchCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.hair = ServiceCategory.objects.create(
            salon=self.salon, name="Hair", sort_order=1)
        self.other_cat = ServiceCategory.objects.create(
            salon=self.other, name="Hair", sort_order=1)
        Service.objects.create(
            category=self.hair, name="Lavender Cut", service_minutes=30)
        Service.objects.create(
            category=self.hair, name="Lavender Trim", service_minutes=20)
        Service.objects.create(
            category=self.hair, name="Retired Cut", service_minutes=30,
            active=False)
        Service.objects.create(
            category=self.other_cat, name="Lavender Cut",
            service_minutes=30)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_service_search", salon_id=self.salon.pk,
            query="Lavender", stdout=out)
        text = out.getvalue()
        self.assertEqual(
            text, export_search_services_csv(self.salon, "Lavender"))
        self.assertEqual(
            text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        self.assertIn("Lavender Cut", text)
        self.assertNotIn("Retired Cut", text)
        # Only this salon's two matches (other salon's excluded).
        self.assertEqual(text.count("Lavender Cut"), 1)

    def test_include_inactive_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_service_search", salon_id=self.salon.pk,
            query="Cut", include_inactive=True, stdout=out)
        text = out.getvalue()
        self.assertEqual(
            text,
            export_search_services_csv(
                self.salon, "Cut", include_inactive=True))
        self.assertIn("Retired Cut", text)

    def test_no_query_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_service_search", salon_id=self.salon.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, export_search_services_csv(self.salon, None))
        self.assertEqual(text, ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "search.csv")
            call_command(
                "export_service_search", salon_id=self.salon.pk,
                query="Lavender", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(
            text, export_search_services_csv(self.salon, "Lavender"))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_service_search", salon_id=999999,
                query="Lavender", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "search.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_service_search", salon_id=self.salon.pk,
                    query="Lavender", output=path, stdout=io.StringIO())
