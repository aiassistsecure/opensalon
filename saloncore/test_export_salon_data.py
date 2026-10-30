"""Tests for the export_salon_data management command (Exit Test part 1).

Synthetic records only — no real salon/client data.
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


class ExportSalonDataTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Export Salon", timezone="America/New_York", currency="USD")
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
        self.opted_in = Client.objects.create(
            salon=self.salon, first_name="Ada", last_name="Optin",
            email="ada@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        self.opted_out = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Optout")
        self.note = ClientNote.objects.create(
            client=self.opted_in, body="Prefers quiet appointments.",
            author_name="Front Desk")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=self.level, online_bookable=False)

    def run_export(self, **kwargs):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        out = io.StringIO()
        call_command("export_salon_data", fh.name, stdout=out, **kwargs)
        with open(fh.name, encoding="utf-8") as exported:
            return json.load(exported), out.getvalue()

    def test_counts_match_created_records(self):
        data, out = self.run_export()
        self.assertIn("EXPORT_SUMMARY", out)
        self.assertEqual(data["counts"], {
            "salons": 1, "service_categories": 1, "services": 1,
            "staff_levels": 1, "service_prices": 1, "clients": 2,
            "client_notes": 1, "staff_members": 1,
        })
        for key, count in data["counts"].items():
            self.assertEqual(len(data[key]), count)

    def test_content_round_trips(self):
        data, _ = self.run_export()
        self.assertEqual(data["salons"][0]["name"], "Export Salon")
        self.assertEqual(data["salons"][0]["timezone"], "America/New_York")
        self.assertEqual(data["service_categories"][0]["name"], "Color")
        service = data["services"][0]
        self.assertEqual(service["name"], "Single Process")
        self.assertEqual(service["external_id"], "svc-1")
        self.assertEqual(service["category_id"], self.category.id)
        self.assertEqual(service["service_minutes"], 45)
        price = data["service_prices"][0]
        self.assertEqual(price["amount"], "85.00")
        self.assertTrue(price["is_from"])
        self.assertEqual(price["service_id"], self.service.id)
        self.assertEqual(price["staff_level_id"], self.level.id)
        self.assertEqual(data["staff_levels"][0]["name"], "Level 6")
        note = data["client_notes"][0]
        self.assertEqual(note["body"], "Prefers quiet appointments.")
        self.assertEqual(note["client_id"], self.opted_in.id)
        staff = data["staff_members"][0]
        self.assertEqual(staff["display_name"], "Stylist One")
        self.assertFalse(staff["online_bookable"])
        self.assertEqual(staff["staff_level_id"], self.level.id)

    def test_opt_in_flags_are_included(self):
        data, _ = self.run_export()
        by_last = {c["last_name"]: c for c in data["clients"]}
        self.assertTrue(by_last["Optin"]["sms_opt_in"])
        self.assertTrue(by_last["Optin"]["email_opt_in"])
        self.assertFalse(by_last["Optout"]["sms_opt_in"])
        self.assertFalse(by_last["Optout"]["email_opt_in"])
        self.assertEqual(by_last["Optin"]["email"], "ada@example.com")

    def test_salon_filter_excludes_other_salons(self):
        other = Salon.objects.create(name="Other Salon")
        Client.objects.create(
            salon=other, first_name="Eve", last_name="Elsewhere")
        data, _ = self.run_export(salon="Export Salon")
        self.assertEqual(data["counts"]["salons"], 1)
        self.assertEqual(data["counts"]["clients"], 2)
        data, _ = self.run_export(salon="Other Salon")
        self.assertEqual(data["counts"]["clients"], 1)
        self.assertEqual(data["clients"][0]["last_name"], "Elsewhere")

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            self.run_export(salon="No Such Salon")

    def test_empty_database_exports_empty_sections(self):
        Salon.objects.all().delete()
        data, _ = self.run_export()
        self.assertTrue(all(count == 0 for count in data["counts"].values()))
