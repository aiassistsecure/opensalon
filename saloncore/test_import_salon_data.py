"""Tests for import_salon_data (Exit Test part 2: the restore side).

Synthetic in-test records only — no real salon/client data. The
centrepiece is a round trip: build records, export them with
export_salon_data, wipe the database, import, and assert the
restored records match on counts and key fields.
"""
import io
import json
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client, ClientNote
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember

MODELS = (Salon, ServiceCategory, Service, StaffLevel, ServicePrice,
          Client, ClientNote, StaffMember)


def _counts():
    return {m.__name__: m.objects.count() for m in MODELS}


class ImportSalonDataTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Restore Salon", timezone="America/New_York", currency="USD")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color", sort_order=1)
        self.service = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-1", description="Root color",
            service_minutes=45, processing_minutes=30, finishing_minutes=15)
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6", sort_order=6)
        self.price = ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"), is_from=True)
        self.client = Client.objects.create(
            salon=self.salon, external_id="cli-1", first_name="Ada",
            last_name="Optin", email="ada@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        self.plain = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Optout")
        self.note = ClientNote.objects.create(
            client=self.client, body="Prefers quiet appointments.",
            author_name="Front Desk")
        self.staff = StaffMember.objects.create(
            salon=self.salon, external_id="staff-1",
            display_name="Stylist One", staff_level=self.level,
            online_bookable=False)

    def temp_path(self):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        return fh.name

    def export(self):
        path = self.temp_path()
        call_command("export_salon_data", path, stdout=io.StringIO())
        return path

    def run_import(self, path):
        out = io.StringIO()
        call_command("import_salon_data", path, stdout=out)
        return out.getvalue()

    def test_round_trip_restores_counts_and_key_fields(self):
        before = _counts()
        path = self.export()
        Salon.objects.all().delete()
        self.assertTrue(all(c == 0 for c in _counts().values()))

        out = self.run_import(path)
        self.assertIn("IMPORT_SUMMARY", out)
        self.assertEqual(_counts(), before)

        salon = Salon.objects.get()
        self.assertEqual(salon.name, "Restore Salon")
        self.assertEqual(salon.timezone, "America/New_York")
        service = Service.objects.get()
        self.assertEqual(service.external_id, "svc-1")
        self.assertEqual(service.name, "Single Process")
        self.assertEqual(service.service_minutes, 45)
        self.assertEqual(service.category.name, "Color")
        self.assertEqual(service.category.salon, salon)
        price = ServicePrice.objects.get()
        self.assertEqual(price.amount, Decimal("85.00"))
        self.assertTrue(price.is_from)
        self.assertEqual(price.service, service)
        self.assertEqual(price.staff_level.name, "Level 6")
        client = Client.objects.get(external_id="cli-1")
        self.assertEqual(client.email, "ada@example.com")
        self.assertTrue(client.sms_opt_in)
        self.assertTrue(client.email_opt_in)
        self.assertEqual(
            Client.objects.filter(first_name="Bob").count(), 1)
        note = ClientNote.objects.get()
        self.assertEqual(note.body, "Prefers quiet appointments.")
        self.assertEqual(note.author_name, "Front Desk")
        self.assertEqual(note.client, client)
        staff = StaffMember.objects.get()
        self.assertEqual(staff.external_id, "staff-1")
        self.assertEqual(staff.display_name, "Stylist One")
        self.assertFalse(staff.online_bookable)
        self.assertEqual(staff.staff_level.name, "Level 6")

    def test_reimport_is_idempotent(self):
        path = self.export()
        Salon.objects.all().delete()
        self.run_import(path)
        after_first = _counts()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(_counts(), after_first)

    def test_reimport_updates_in_place(self):
        path = self.export()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["service_prices"][0]["amount"] = "90.00"
        data["clients"][0]["phone"] = "555-0199"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        self.run_import(path)
        self.assertEqual(ServicePrice.objects.count(), 1)
        self.assertEqual(
            ServicePrice.objects.get().amount, Decimal("90.00"))
        self.assertEqual(Client.objects.count(), 2)
        self.assertEqual(
            Client.objects.get(external_id="cli-1").phone, "555-0199")

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            call_command("import_salon_data", "/nonexistent/nope.json")

    def test_invalid_json_raises_and_changes_nothing(self):
        path = self.temp_path()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        before = _counts()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(_counts(), before)

    def test_missing_section_raises(self):
        path = self.temp_path()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"salons": []}, fh)
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)

    def test_dangling_reference_raises_and_changes_nothing(self):
        path = self.export()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["services"][0]["category_id"] = 999999
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        # Validate-before-write: not even the salons were restored.
        self.assertTrue(all(c == 0 for c in _counts().values()))

    def test_dangling_reference_in_late_section_writes_nothing(self):
        # staff_members is the LAST section written; every earlier
        # section is valid. Pre-validation must still write zero rows.
        path = self.export()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["staff_members"][0]["staff_level_id"] = 999999
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertTrue(all(c == 0 for c in _counts().values()))
