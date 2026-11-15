"""Tests for export_salon_data --salon-id (id-selected salon).

Synthetic records only — no real salon/client data.
"""
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client
from saloncore.models import Salon


class ExportSalonDataSalonIdTests(TestCase):
    def setUp(self):
        self.target = Salon.objects.create(name="Target Salon")
        self.other = Salon.objects.create(name="Other Salon")
        Client.objects.create(
            salon=self.target, first_name="Ada", last_name="Target")
        Client.objects.create(
            salon=self.other, first_name="Bob", last_name="Other")

    def run_export(self, **kwargs):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        out = io.StringIO()
        call_command("export_salon_data", fh.name, stdout=out, **kwargs)
        with open(fh.name, encoding="utf-8") as exported:
            return json.load(exported), out.getvalue()

    def test_salon_id_selects_existing_salon(self):
        data, out = self.run_export(salon_id=self.target.pk)
        self.assertIn("EXPORT_SUMMARY", out)
        self.assertEqual([s["id"] for s in data["salons"]], [self.target.pk])
        self.assertEqual([s["name"] for s in data["salons"]], ["Target Salon"])
        self.assertEqual(data["counts"]["salons"], 1)
        self.assertEqual(data["counts"]["clients"], 1)
        self.assertEqual(data["clients"][0]["last_name"], "Target")

    def test_salon_id_unknown_raises_and_emits_nothing(self):
        path = os.path.join(tempfile.mkdtemp(), "export.json")
        out = io.StringIO()
        with self.assertRaises(CommandError):
            call_command("export_salon_data", path, stdout=out,
                         salon_id=999999)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(out.getvalue(), "")

    def test_salon_id_takes_precedence_over_salon_name(self):
        data, _ = self.run_export(salon="Other Salon",
                                  salon_id=self.target.pk)
        self.assertEqual([s["name"] for s in data["salons"]], ["Target Salon"])
        self.assertEqual(data["clients"][0]["last_name"], "Target")

    def test_salon_id_precedence_even_with_unknown_name(self):
        data, _ = self.run_export(salon="No Such Salon",
                                  salon_id=self.target.pk)
        self.assertEqual([s["name"] for s in data["salons"]], ["Target Salon"])

    def test_name_path_unchanged(self):
        data, _ = self.run_export(salon="Other Salon")
        self.assertEqual([s["name"] for s in data["salons"]], ["Other Salon"])
        self.assertEqual(data["clients"][0]["last_name"], "Other")

    def test_salon_id_with_csv_format(self):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8")
        fh.close()
        out = io.StringIO()
        call_command("export_salon_data", fh.name, stdout=out,
                     salon_id=self.target.pk, format="csv")
        with open(fh.name, encoding="utf-8") as exported:
            text = exported.read()
        self.assertIn("EXPORT_SUMMARY", out.getvalue())
        self.assertIn("Target Salon", text)
        self.assertNotIn("Other Salon", text)
