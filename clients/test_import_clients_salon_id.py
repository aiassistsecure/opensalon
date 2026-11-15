"""Tests for the import_clients --salon-id bridge.

--salon-id selects an existing salon by pk and takes precedence
over --salon; a nonexistent id raises CommandError and writes
nothing; without --salon-id the name path is unchanged.
Unit logic only, no real salon data.
"""
import io
import json
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client
from saloncore.models import Salon

PAYLOAD = [
    {"clientId": "sid-1", "firstName": "Ida", "lastName": "Selected",
     "email": "ida.selected@example.com", "mobile": "555-0500"},
    {"clientId": "sid-2", "firstName": "Second", "lastName": "Row",
     "email": "", "mobile": "555-0501"},
]


def _write(payload):
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fh)
    fh.close()
    return fh.name


class ImportClientsSalonIdTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Id Salon")

    def run_import(self, payload=PAYLOAD, **kwargs):
        out = io.StringIO()
        call_command("import_clients", _write(payload), stdout=out, **kwargs)
        return out.getvalue()

    def test_salon_id_selects_existing_salon(self):
        out = self.run_import(salon_id=self.salon.pk)
        self.assertIn('"created": 2', out)
        self.assertIn('"salon": "Id Salon"', out)
        self.assertEqual(
            Client.objects.filter(salon=self.salon).count(), 2)
        # The default name path was not used: no new salon created.
        self.assertEqual(Salon.objects.count(), 1)
        self.assertFalse(Salon.objects.filter(name="My Salon").exists())

    def test_salon_id_cli_flag_selects_existing_salon(self):
        out = io.StringIO()
        call_command(
            "import_clients", _write(PAYLOAD),
            "--salon-id", str(self.salon.pk), stdout=out)
        self.assertIn('"created": 2', out.getvalue())
        self.assertEqual(
            Client.objects.filter(salon=self.salon).count(), 2)

    def test_salon_id_nonexistent_raises_and_writes_nothing(self):
        missing = self.salon.pk + 1000
        with self.assertRaises(CommandError):
            self.run_import(salon_id=missing)
        self.assertEqual(Client.objects.count(), 0)
        # Only the pre-existing salon remains; nothing was created.
        self.assertEqual(Salon.objects.count(), 1)
        self.assertFalse(Salon.objects.filter(name="My Salon").exists())

    def test_salon_id_takes_precedence_over_salon_name(self):
        out = self.run_import(
            salon_id=self.salon.pk, salon="Different Name")
        self.assertIn('"salon": "Id Salon"', out)
        self.assertEqual(
            Client.objects.filter(salon=self.salon).count(), 2)
        self.assertFalse(
            Salon.objects.filter(name="Different Name").exists())
        self.assertEqual(Salon.objects.count(), 1)

    def test_name_path_unchanged_without_salon_id(self):
        out = self.run_import(salon="Named Salon")
        self.assertIn('"created": 2', out)
        named = Salon.objects.get(name="Named Salon")
        self.assertEqual(Client.objects.filter(salon=named).count(), 2)
        self.assertEqual(Client.objects.filter(salon=self.salon).count(), 0)

    def test_salon_id_dry_run_previews_that_salon_and_writes_nothing(self):
        self.run_import(salon_id=self.salon.pk)
        out = io.StringIO()
        call_command(
            "import_clients", _write(PAYLOAD), dry_run=True,
            salon_id=self.salon.pk, stdout=out)
        report = json.loads(out.getvalue())
        preview = report["import_preview"]
        self.assertEqual(preview["salon"], "Id Salon")
        self.assertTrue(preview["salon_exists"])
        self.assertEqual(preview["would_unchanged"], 2)
        self.assertEqual(Client.objects.count(), 2)
        self.assertEqual(Salon.objects.count(), 1)

    def test_salon_id_nonexistent_dry_run_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "import_clients", _write(PAYLOAD), dry_run=True,
                salon_id=self.salon.pk + 1000, stdout=io.StringIO())
        self.assertEqual(Client.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 1)
