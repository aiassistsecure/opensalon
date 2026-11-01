"""Tests for the export_salon_data management command (Exit Test part 1).

Synthetic records only — no real salon/client data.
"""
import io
import json
import tempfile
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment, AppointmentNote
from checkout.models import Payment, Sale, SaleItem
from catalog.models import Product, StockMovement
from clients.models import Client, ClientNote
from saloncore.models import (
    PriceChange,
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import (
    AttendanceRecord,
    RosterPattern,
    ShiftOverride,
    StaffMember,
)


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
            "roster_patterns": 0, "shift_overrides": 0,
            "sales": 0, "sale_items": 0, "sale_payments": 0,
            "stock_movements": 0, "attendance_records": 0,
            "price_changes": 0,
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

    def test_salon_row_carries_every_salon_field_with_full_values(self):
        # Salon self-fields (cycle 72): the salons row must carry
        # EVERY concrete field of the real Salon model — the key set
        # is derived from the model itself, so a future Salon field
        # that the exporter forgets fails this test by name. There
        # is no SalonSettings model in any app (searched saloncore,
        # clients, team, bookings, checkout, catalog, messaging,
        # onlinebooking, insights): the salon profile IS the Salon
        # record (name/timezone/currency), per webui's settings page.
        self.salon.refresh_from_db()
        data, _ = self.run_export()
        row = data["salons"][0]
        self.assertEqual(
            set(row), {f.name for f in Salon._meta.fields})
        self.assertEqual(row["id"], self.salon.id)
        self.assertEqual(row["name"], "Export Salon")
        self.assertEqual(row["timezone"], "America/New_York")
        self.assertEqual(row["currency"], "USD")
        self.assertEqual(row["created_at"],
                         self.salon.created_at.isoformat())
        self.assertEqual(row["updated_at"],
                         self.salon.updated_at.isoformat())

    def test_salon_filter_scopes_salon_row_full_values(self):
        Salon.objects.create(
            name="Other Salon", timezone="Europe/Paris", currency="EUR")
        data, _ = self.run_export(salon="Other Salon")
        self.assertEqual(data["counts"]["salons"], 1)
        row = data["salons"][0]
        self.assertEqual(row["name"], "Other Salon")
        self.assertEqual(row["timezone"], "Europe/Paris")
        self.assertEqual(row["currency"], "EUR")

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


class ExportRosterTests(TestCase):
    """Roster leg: export emits roster patterns + shift overrides."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Roster Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            external_id="staff-r")
        self.pattern = RosterPattern.objects.create(
            staff_member=self.staff, weekday=RosterPattern.Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(17, 0))
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=RosterPattern.Weekday.SATURDAY,
            start_time=time(10, 0), end_time=time(14, 0), active=False)
        self.off = ShiftOverride.objects.create(
            staff_member=self.staff, date=date(2026, 11, 7), is_off=True)
        self.placed = ShiftOverride.objects.create(
            staff_member=self.staff, date=date(2026, 11, 14),
            is_off=False, start_time=time(9, 0), end_time=time(13, 0))

    def run_export(self, **kwargs):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        call_command("export_salon_data", fh.name,
                     stdout=io.StringIO(), **kwargs)
        with open(fh.name, encoding="utf-8") as exported:
            return json.load(exported)

    def test_export_emits_both_sections_with_all_fields(self):
        data = self.run_export()
        self.assertEqual(data["counts"]["roster_patterns"], 2)
        self.assertEqual(data["counts"]["shift_overrides"], 2)
        by_weekday = {r["weekday"]: r for r in data["roster_patterns"]}
        mon = by_weekday[0]
        self.assertEqual(mon["id"], self.pattern.id)
        self.assertEqual(mon["staff_member_id"], self.staff.id)
        self.assertEqual(mon["staff_member_external_id"], "staff-r")
        self.assertEqual(mon["start_time"], "09:00:00")
        self.assertEqual(mon["end_time"], "17:00:00")
        self.assertTrue(mon["active"])
        self.assertFalse(by_weekday[5]["active"])
        by_date = {o["date"]: o for o in data["shift_overrides"]}
        off = by_date["2026-11-07"]
        self.assertEqual(off["id"], self.off.id)
        self.assertTrue(off["is_off"])
        self.assertIsNone(off["start_time"])
        self.assertIsNone(off["end_time"])
        placed = by_date["2026-11-14"]
        self.assertFalse(placed["is_off"])
        self.assertEqual(placed["start_time"], "09:00:00")
        self.assertEqual(placed["end_time"], "13:00:00")

    def test_salon_filter_scopes_roster_sections(self):
        other = Salon.objects.create(name="Other Salon")
        other_staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        RosterPattern.objects.create(
            staff_member=other_staff, weekday=2,
            start_time=time(9, 0), end_time=time(12, 0))
        ShiftOverride.objects.create(
            staff_member=other_staff, date=date(2026, 11, 8), is_off=True)
        data = self.run_export(salon="Roster Salon")
        self.assertEqual(data["counts"]["roster_patterns"], 2)
        self.assertEqual(data["counts"]["shift_overrides"], 2)
        data = self.run_export(salon="Other Salon")
        self.assertEqual(data["counts"]["roster_patterns"], 1)
        self.assertEqual(data["counts"]["shift_overrides"], 1)


class ExportSalesTests(TestCase):
    """Sales leg: export emits sales, sale items and sale payments.

    Provider-agnostic founding rule: Payment.provider_reference is
    a provider identifier and must never appear in the export.
    """

    def setUp(self):
        self.salon = Salon.objects.create(name="Sales Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")
        self.service = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-s", service_minutes=45)
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", price=Decimal("24.50"),
            external_id="prod-s")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Ada", last_name="Optin",
            external_id="cli-s")
        self.sale = Sale.objects.create(
            salon=self.salon, client=self.client,
            status=Sale.Status.COMPLETED)
        self.item_service = SaleItem.objects.create(
            sale=self.sale, kind=SaleItem.Kind.SERVICE,
            service=self.service, description="Single Process",
            quantity=1, unit_price=Decimal("85.00"))
        self.item_product = SaleItem.objects.create(
            sale=self.sale, kind=SaleItem.Kind.PRODUCT,
            product=self.product, description="Shampoo",
            quantity=2, unit_price=Decimal("24.50"))
        self.payment = Payment.objects.create(
            sale=self.sale, method=Payment.Method.CASH,
            amount=Decimal("134.00"), status=Payment.Status.COMPLETED,
            provider_reference="PROV-SECRET-1")
        self.walkin = Sale.objects.create(salon=self.salon)

    def run_export(self, **kwargs):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        call_command("export_salon_data", fh.name,
                     stdout=io.StringIO(), **kwargs)
        with open(fh.name, encoding="utf-8") as exported:
            raw = exported.read()
        return json.loads(raw), raw

    def test_export_emits_sales_sections_with_all_fields(self):
        data, _ = self.run_export()
        self.assertEqual(data["counts"]["sales"], 2)
        self.assertEqual(data["counts"]["sale_items"], 2)
        self.assertEqual(data["counts"]["sale_payments"], 1)
        sale = next(s for s in data["sales"] if s["client_id"])
        self.assertEqual(sale["salon_id"], self.salon.id)
        self.assertEqual(sale["client_external_id"], "cli-s")
        self.assertEqual(sale["status"], "completed")
        self.assertEqual(sale["void_reason"], "")
        walkin = next(s for s in data["sales"] if not s["client_id"])
        self.assertIsNone(walkin["client_external_id"])
        items = {i["kind"]: i for i in data["sale_items"]}
        self.assertEqual(items["service"]["service_external_id"], "svc-s")
        self.assertEqual(items["service"]["unit_price"], "85.00")
        self.assertEqual(items["product"]["product_external_id"], "prod-s")
        self.assertEqual(items["product"]["quantity"], 2)
        pay = data["sale_payments"][0]
        self.assertEqual(pay["sale_id"], self.sale.id)
        self.assertEqual(pay["method"], "cash")
        self.assertEqual(pay["amount"], "134.00")
        self.assertEqual(pay["status"], "completed")

    def test_export_never_carries_provider_reference(self):
        data, raw = self.run_export()
        self.assertNotIn("provider_reference", raw)
        self.assertNotIn("PROV-SECRET-1", raw)
        for row in data["sale_payments"]:
            self.assertNotIn("provider_reference", row)

    def test_salon_filter_scopes_sales(self):
        other = Salon.objects.create(name="Other Salon")
        Sale.objects.create(salon=other)
        data, _ = self.run_export(salon="Sales Salon")
        self.assertEqual(data["counts"]["sales"], 2)
        self.assertEqual(data["counts"]["sale_items"], 2)
        data, _ = self.run_export(salon="Other Salon")
        self.assertEqual(data["counts"]["sales"], 1)
        self.assertEqual(data["counts"]["sale_items"], 0)
        self.assertEqual(data["counts"]["sale_payments"], 0)


class ExportStockMovementsTests(TestCase):
    """Stock movements leg: export scoped via the product's salon."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Stock Salon")
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", price=Decimal("24.50"),
            external_id="prod-m")
        self.receive = StockMovement.objects.create(
            product=self.product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=10, note="Delivery")
        self.sale_move = StockMovement.objects.create(
            product=self.product, kind=StockMovement.Kind.SALE,
            quantity_delta=-1)

    def run_export(self, **kwargs):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        call_command("export_salon_data", fh.name,
                     stdout=io.StringIO(), **kwargs)
        with open(fh.name, encoding="utf-8") as exported:
            return json.load(exported)

    def test_export_emits_stock_movements_with_all_fields(self):
        data = self.run_export()
        self.assertEqual(data["counts"]["stock_movements"], 2)
        by_kind = {m["kind"]: m for m in data["stock_movements"]}
        recv = by_kind["receive"]
        self.assertEqual(recv["product_id"], self.product.id)
        self.assertEqual(recv["product_external_id"], "prod-m")
        self.assertEqual(recv["quantity_delta"], 10)
        self.assertIsInstance(recv["quantity_delta"], int)
        self.assertEqual(recv["note"], "Delivery")
        self.assertIsNotNone(recv["created_at"])
        self.assertEqual(by_kind["sale"]["quantity_delta"], -1)
        self.assertEqual(by_kind["sale"]["note"], "")

    def test_salon_filter_scopes_stock_movements_via_product(self):
        other = Salon.objects.create(name="Other Salon")
        other_product = Product.objects.create(
            salon=other, name="Gel", price=Decimal("9.00"))
        StockMovement.objects.create(
            product=other_product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=5)
        data = self.run_export(salon="Stock Salon")
        self.assertEqual(data["counts"]["stock_movements"], 2)
        data = self.run_export(salon="Other Salon")
        self.assertEqual(data["counts"]["stock_movements"], 1)
        self.assertEqual(
            data["stock_movements"][0]["product_id"], other_product.id)


class ExportAttendanceRecordsTests(TestCase):
    """Attendance leg: export scoped via the staff member's salon."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Clock Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            external_id="staff-a")
        self.check_in = AttendanceRecord.objects.create(
            staff_member=self.staff,
            event_type=AttendanceRecord.EventType.CHECK_IN,
            recorded_at=datetime(2026, 10, 3, 9, 0,
                                 tzinfo=dt_timezone.utc),
            note="On time")
        self.check_out = AttendanceRecord.objects.create(
            staff_member=self.staff,
            event_type=AttendanceRecord.EventType.CHECK_OUT,
            recorded_at=datetime(2026, 10, 3, 17, 0,
                                 tzinfo=dt_timezone.utc))

    def run_export(self, **kwargs):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        call_command("export_salon_data", fh.name,
                     stdout=io.StringIO(), **kwargs)
        with open(fh.name, encoding="utf-8") as exported:
            return json.load(exported)

    def test_export_emits_attendance_records_with_all_fields(self):
        data = self.run_export()
        self.assertEqual(data["counts"]["attendance_records"], 2)
        by_type = {r["event_type"]: r for r in data["attendance_records"]}
        rec = by_type["check_in"]
        self.assertEqual(rec["staff_member_id"], self.staff.id)
        self.assertEqual(rec["staff_member_external_id"], "staff-a")
        self.assertEqual(
            rec["recorded_at"], "2026-10-03T09:00:00+00:00")
        self.assertEqual(rec["note"], "On time")
        self.assertEqual(by_type["check_out"]["note"], "")

    def test_salon_filter_scopes_attendance_via_staff_member(self):
        other = Salon.objects.create(name="Other Salon")
        other_staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        AttendanceRecord.objects.create(
            staff_member=other_staff,
            event_type=AttendanceRecord.EventType.CHECK_IN,
            recorded_at=datetime(2026, 10, 3, 8, 0,
                                 tzinfo=dt_timezone.utc))
        data = self.run_export(salon="Clock Salon")
        self.assertEqual(data["counts"]["attendance_records"], 2)
        data = self.run_export(salon="Other Salon")
        self.assertEqual(data["counts"]["attendance_records"], 1)
        self.assertEqual(
            data["attendance_records"][0]["staff_member_id"],
            other_staff.id)


class ExportPriceChangesTests(TestCase):
    """Price changes leg: export scoped via price -> service chain."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Audit Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")
        self.service = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-pc", service_minutes=45)
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6", sort_order=6)
        self.price = ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"))
        self.rise = PriceChange.objects.create(
            service_price=self.price, old_amount=Decimal("75.00"),
            new_amount=Decimal("85.00"), changed_by="Manager",
            note="Annual rise")
        self.first = PriceChange.objects.create(
            service_price=self.price, old_amount=None,
            new_amount=Decimal("75.00"))

    def run_export(self, **kwargs):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        call_command("export_salon_data", fh.name,
                     stdout=io.StringIO(), **kwargs)
        with open(fh.name, encoding="utf-8") as exported:
            return json.load(exported)

    def test_export_emits_price_changes_with_all_fields(self):
        data = self.run_export()
        self.assertEqual(data["counts"]["price_changes"], 2)
        by_new = {c["new_amount"]: c for c in data["price_changes"]}
        rise = by_new["85.00"]
        self.assertEqual(rise["id"], self.rise.id)
        self.assertEqual(rise["service_price_id"], self.price.id)
        self.assertEqual(rise["service_id"], self.service.id)
        self.assertEqual(rise["service_external_id"], "svc-pc")
        self.assertEqual(rise["staff_level_id"], self.level.id)
        self.assertEqual(rise["old_amount"], "75.00")
        self.assertIsInstance(rise["old_amount"], str)
        self.assertEqual(rise["changed_by"], "Manager")
        self.assertEqual(rise["note"], "Annual rise")
        self.assertEqual(
            rise["changed_at"], self.rise.changed_at.isoformat())
        self.assertIsNone(by_new["75.00"]["old_amount"])

    def test_salon_filter_scopes_price_changes_via_service(self):
        other = Salon.objects.create(name="Other Salon")
        other_category = ServiceCategory.objects.create(
            salon=other, name="Color")
        other_service = Service.objects.create(
            category=other_category, name="Cut", service_minutes=30)
        other_level = StaffLevel.objects.create(salon=other, name="L1")
        other_price = ServicePrice.objects.create(
            service=other_service, staff_level=other_level,
            amount=Decimal("40.00"))
        PriceChange.objects.create(
            service_price=other_price, new_amount=Decimal("40.00"))
        data = self.run_export(salon="Audit Salon")
        self.assertEqual(data["counts"]["price_changes"], 2)
        data = self.run_export(salon="Other Salon")
        self.assertEqual(data["counts"]["price_changes"], 1)
        self.assertEqual(
            data["price_changes"][0]["service_price_id"], other_price.id)
