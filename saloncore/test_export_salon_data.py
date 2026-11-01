"""Tests for the export_salon_data management command (Exit Test part 1).

Synthetic records only — no real salon/client data.
"""
import io
import json
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment, AppointmentNote
from catalog.models import Product
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
            "appointments": 0, "appointment_notes": 0, "products": 0,
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


class ExportAppointmentsTests(TestCase):
    """EXP-APPT-a: appointments + appointment notes in the export.

    AppointmentNote is a separate bookings model (notes do NOT live
    on Appointment itself), so it exports as its own section.
    """

    def setUp(self):
        self.salon = Salon.objects.create(
            name="Appt Salon", timezone="America/New_York", currency="USD")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color", sort_order=1)
        self.service = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-9", service_minutes=45)
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6", sort_order=6)
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"), is_from=True)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Ada", last_name="Optin",
            external_id="cli-9")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            external_id="staff-9", staff_level=self.level)
        self.start = datetime(2026, 11, 2, 14, 0, tzinfo=dt_timezone.utc)
        self.appt = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, external_id="appt-1",
            start=self.start, end=self.start + timedelta(minutes=45),
            status=Appointment.Status.CONFIRMED,
            origin=Appointment.Origin.PHONE,
            price_override=Decimal("80.00"))
        self.orphan = Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=None,
            service_name="Off-book Service",
            start=self.start + timedelta(days=1),
            end=self.start + timedelta(days=1, minutes=30),
            status=Appointment.Status.BOOKED)
        self.note = AppointmentNote.objects.create(
            appointment=self.appt, body="Allergic to ammonia.",
            author_name="Front Desk")
        AppointmentNote.objects.create(
            appointment=self.appt, body="Arrives early.")

    def run_export(self, **kwargs):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        out = io.StringIO()
        call_command("export_salon_data", fh.name, stdout=out, **kwargs)
        with open(fh.name, encoding="utf-8") as exported:
            return json.load(exported), out.getvalue()

    def test_appointment_sections_present_with_counts(self):
        data, _ = self.run_export()
        self.assertEqual(data["counts"]["appointments"], 2)
        self.assertEqual(data["counts"]["appointment_notes"], 2)
        self.assertEqual(len(data["appointments"]), 2)
        self.assertEqual(len(data["appointment_notes"]), 2)

    def test_appointment_field_values(self):
        data, _ = self.run_export()
        by_ext = {a["external_id"]: a for a in data["appointments"]}
        appt = by_ext["appt-1"]
        self.assertEqual(appt["id"], self.appt.id)
        self.assertEqual(appt["client_id"], self.client.id)
        self.assertEqual(appt["client_external_id"], "cli-9")
        self.assertEqual(appt["staff_member_id"], self.staff.id)
        self.assertEqual(appt["staff_member_external_id"], "staff-9")
        self.assertEqual(appt["service_id"], self.service.id)
        self.assertEqual(appt["service_external_id"], "svc-9")
        self.assertEqual(appt["start"], self.start.isoformat())
        self.assertEqual(
            appt["end"], (self.start + timedelta(minutes=45)).isoformat())
        self.assertEqual(appt["status"], "confirmed")
        self.assertEqual(appt["origin"], "phone")
        self.assertEqual(appt["price_override"], "80.00")
        orphan = by_ext[""]
        self.assertIsNone(orphan["service_id"])
        self.assertIsNone(orphan["service_external_id"])
        self.assertEqual(orphan["service_name"], "Off-book Service")
        self.assertIsNone(orphan["price_override"])

    def test_appointment_note_field_values(self):
        data, _ = self.run_export()
        bodies = {n["body"] for n in data["appointment_notes"]}
        self.assertEqual(bodies, {"Allergic to ammonia.", "Arrives early."})
        note = next(
            n for n in data["appointment_notes"]
            if n["body"] == "Allergic to ammonia.")
        self.assertEqual(note["id"], self.note.id)
        self.assertEqual(note["appointment_id"], self.appt.id)
        self.assertEqual(note["author_name"], "Front Desk")

    def test_preexisting_sections_unchanged(self):
        data, _ = self.run_export()
        self.assertEqual(data["counts"]["salons"], 1)
        self.assertEqual(data["counts"]["service_categories"], 1)
        self.assertEqual(data["counts"]["services"], 1)
        self.assertEqual(data["counts"]["staff_levels"], 1)
        self.assertEqual(data["counts"]["service_prices"], 1)
        self.assertEqual(data["counts"]["clients"], 1)
        self.assertEqual(data["counts"]["client_notes"], 0)
        self.assertEqual(data["counts"]["staff_members"], 1)
        self.assertEqual(data["services"][0]["external_id"], "svc-9")
        self.assertEqual(data["clients"][0]["external_id"], "cli-9")
        self.assertEqual(data["staff_members"][0]["external_id"], "staff-9")

    def test_salon_filter_excludes_other_salons_appointments(self):
        other = Salon.objects.create(name="Other Salon")
        other_client = Client.objects.create(
            salon=other, first_name="Eve", last_name="Elsewhere")
        other_staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        Appointment.objects.create(
            client=other_client, staff_member=other_staff, service=None,
            start=self.start, end=self.start + timedelta(minutes=30))
        data, _ = self.run_export(salon="Appt Salon")
        self.assertEqual(data["counts"]["appointments"], 2)
        self.assertEqual(data["counts"]["appointment_notes"], 2)


class ExportPayloadTests(TestCase):
    """Payload leg: export emits payloads verbatim where models carry one."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Payload Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")
        self.service_payload = {"z_key": 1, "a_key": {"nested": [1, 2]}}
        self.service = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-p", service_minutes=45,
            payload=self.service_payload)
        self.client_payload = {"legacy": {"id": 7, "tags": ["x", "y"]}}
        self.client = Client.objects.create(
            salon=self.salon, first_name="Ada", last_name="Optin",
            external_id="cli-p", payload=self.client_payload)
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            external_id="staff-p")
        self.start = datetime(2026, 11, 2, 14, 0,
                              tzinfo=dt_timezone.utc)
        self.appt_payload = {"price": "85.00", "source_ref": "r-1"}
        self.appt = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, external_id="appt-p",
            start=self.start, end=self.start + timedelta(minutes=45),
            payload=self.appt_payload)

    def run_export(self):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        call_command("export_salon_data", fh.name, stdout=io.StringIO())
        with open(fh.name, encoding="utf-8") as exported:
            return json.load(exported)

    def test_export_emits_payloads_for_clients_services_appointments(self):
        data = self.run_export()
        self.assertEqual(data["clients"][0]["payload"], self.client_payload)
        self.assertEqual(data["services"][0]["payload"], self.service_payload)
        self.assertEqual(
            data["appointments"][0]["payload"], self.appt_payload)

    def test_staff_members_section_has_no_payload(self):
        # StaffMember carries no payload field — none is invented.
        data = self.run_export()
        self.assertNotIn("payload", data["staff_members"][0])
        self.assertFalse(hasattr(StaffMember, "payload"))


class ExportProductsTests(TestCase):
    """Products leg: export emits catalog.Product rows faithfully."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Product Salon")
        self.payload = {"legacy": {"id": 11, "tags": ["retail"]}}
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SKU-1",
            barcode="012345678905", price=Decimal("24.50"),
            cost_price=Decimal("10.25"), active=False,
            external_id="prod-1", brand_name="BrandCo",
            category_name="Hair Care", product_type="retail",
            payload=self.payload)
        self.plain = Product.objects.create(
            salon=self.salon, name="Comb", price=Decimal("5.00"))

    def run_export(self, **kwargs):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        call_command("export_salon_data", fh.name,
                     stdout=io.StringIO(), **kwargs)
        with open(fh.name, encoding="utf-8") as exported:
            return json.load(exported)

    def test_export_emits_products_with_all_fields(self):
        data = self.run_export()
        self.assertEqual(data["counts"]["products"], 2)
        self.assertEqual(len(data["products"]), 2)
        by_ext = {p["external_id"]: p for p in data["products"]}
        row = by_ext["prod-1"]
        self.assertEqual(row["id"], self.product.id)
        self.assertEqual(row["salon_id"], self.salon.id)
        self.assertEqual(row["name"], "Shampoo")
        self.assertEqual(row["sku"], "SKU-1")
        self.assertEqual(row["barcode"], "012345678905")
        self.assertEqual(row["price"], "24.50")
        self.assertEqual(row["cost_price"], "10.25")
        self.assertFalse(row["active"])
        self.assertEqual(row["brand_name"], "BrandCo")
        self.assertEqual(row["category_name"], "Hair Care")
        self.assertEqual(row["product_type"], "retail")
        self.assertEqual(row["payload"], self.payload)
        plain = by_ext[""]
        self.assertEqual(plain["name"], "Comb")
        self.assertEqual(plain["price"], "5.00")
        self.assertIsNone(plain["cost_price"])
        self.assertEqual(plain["payload"], {})

    def test_salon_filter_scopes_products(self):
        other = Salon.objects.create(name="Other Salon")
        Product.objects.create(
            salon=other, name="Elsewhere Gel", price=Decimal("9.00"))
        data = self.run_export(salon="Product Salon")
        self.assertEqual(data["counts"]["products"], 2)
        data = self.run_export(salon="Other Salon")
        self.assertEqual(data["counts"]["products"], 1)
        self.assertEqual(data["products"][0]["name"], "Elsewhere Gel")
