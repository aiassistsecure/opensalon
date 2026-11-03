"""import_salon_data --dry-run slice-3 preview (cycle 144).

Slice-3 sections (appointments, appointment_notes, products)
gain the same read-only import_preview as slices 1-2:
would-create / would-update / would-unchanged / would-skip
counts mirroring the writer's identity rules.
Writer never entered in dry-run.
"""
import io
import json
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from bookings.models import Appointment, AppointmentNote
from catalog.models import Product
from clients.models import Client
from saloncore.management.commands.import_salon_data import SECTIONS
from saloncore.models import (
    Salon, Service, ServiceCategory, ServicePrice, StaffLevel)
from saloncore.test_import_salon_data import _minimal_data
from team.models import StaffMember

SLICE3 = ("appointments", "appointment_notes", "products")
MODELS = (Appointment, AppointmentNote, Product)
START = datetime(2026, 11, 2, 14, 0, tzinfo=dt_timezone.utc)


def _data():
    data = _minimal_data()
    data["appointment_notes"] = [
        {"id": 91, "appointment_id": 70, "body": "Arrives early.",
         "author_name": "Front Desk",
         "created_at": "2026-01-01T09:00:00+00:00"}]
    data["products"] = [
        {"id": 80, "salon_id": 1, "external_id": "prod-1",
         "name": "Shampoo", "sku": "SKU-1", "barcode": "BC-1",
         "price": "25.00", "cost_price": "10.00", "active": True,
         "brand_name": "Brand", "category_name": "Retail",
         "product_type": "retail"}]
    return data


class ImportSalonDataPreviewSlice3Tests(TestCase):
    def write_data(self, data):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, fh)
        fh.close()
        return fh.name

    def run_dry(self, data):
        out = io.StringIO()
        call_command("import_salon_data", self.write_data(data),
                     dry_run=True, stdout=out)
        return json.loads(out.getvalue())

    def counts(self):
        return {m.__name__: m.objects.count() for m in MODELS}

    def store_matching(self):
        salon = Salon.objects.create(
            name="TF6 Salon", timezone="UTC", currency="USD")
        category = ServiceCategory.objects.create(
            salon=salon, name="Color", sort_order=1, active=True)
        level = StaffLevel.objects.create(
            salon=salon, name="Level 6", sort_order=6, active=True)
        service = Service.objects.create(
            category=category, external_id="svc-1",
            name="Single Process", description="",
            service_minutes=45, processing_minutes=0,
            finishing_minutes=0, active=True)
        ServicePrice.objects.create(
            service=service, staff_level=level,
            amount=Decimal("85.00"), is_from=True, active=True)
        client = Client.objects.create(
            salon=salon, external_id="cli-1", first_name="Ada",
            last_name="Optin", email="", phone="", sms_opt_in=False,
            email_opt_in=False, active=True)
        staff = StaffMember.objects.create(
            salon=salon, external_id="staff-1",
            display_name="Stylist One", staff_level=level,
            online_bookable=True, active=True, pin="", email="")
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=service,
            external_id="appt-1", service_name="", start=START,
            end=START + timedelta(minutes=45),
            status=Appointment.Status.BOOKED,
            origin=Appointment.Origin.PHONE, price_override=None)
        AppointmentNote.objects.create(
            appointment=appt, body="Arrives early.",
            author_name="Front Desk")
        Product.objects.create(
            salon=salon, external_id="prod-1", name="Shampoo",
            sku="SKU-1", barcode="BC-1", price=Decimal("25.00"),
            cost_price=Decimal("10.00"), active=True,
            brand_name="Brand", category_name="Retail",
            product_type="retail")
        return salon

    def test_preview_present_on_slice3_sections(self):
        reports = self.run_dry(_data())
        self.assertEqual(set(reports), set(SECTIONS))
        for section in SLICE3:
            self.assertIn("import_preview", reports[section], section)

    def test_would_create_all_slice3_on_empty_db(self):
        reports = self.run_dry(_data())
        for section in SLICE3:
            preview = reports[section]["import_preview"]
            self.assertEqual(
                (preview["total"], preview["would_create"],
                 preview["would_update"], preview["would_unchanged"],
                 preview["would_skip"]), (1, 1, 0, 0, 0), section)
            self.assertEqual(preview["skipped_rows"], [], section)

    def test_would_unchanged_against_matching_stored(self):
        self.store_matching()
        reports = self.run_dry(_data())
        for section in SLICE3:
            preview = reports[section]["import_preview"]
            self.assertEqual(preview["would_unchanged"], 1, section)
            self.assertEqual(preview["would_create"], 0, section)

    def test_would_update_when_stored_fields_differ(self):
        self.store_matching()
        data = _data()
        data["appointments"][0]["status"] = "confirmed"
        data["products"][0]["price"] = "30.00"
        reports = self.run_dry(data)
        for section in ("appointments", "products"):
            self.assertEqual(
                reports[section]["import_preview"]["would_update"],
                1, section)
        # A note's body is its identity: nothing in its (empty)
        # defaults can update, so it stays unchanged.
        self.assertEqual(
            reports["appointment_notes"]["import_preview"]
            ["would_unchanged"], 1)

    def test_repeat_row_in_file_judged_against_first_row(self):
        data = _data()
        data["appointments"].append(dict(data["appointments"][0], id=71))
        data["products"].append(
            dict(data["products"][0], id=81, price="30.00"))
        reports = self.run_dry(data)
        appt = reports["appointments"]["import_preview"]
        self.assertEqual(
            (appt["would_create"], appt["would_unchanged"]), (1, 1))
        product = reports["products"]["import_preview"]
        self.assertEqual(
            (product["would_create"], product["would_update"]), (1, 1))

    def test_no_external_id_identities_match_stored(self):
        self.store_matching()
        data = _data()
        # Drop the external ids: appointments key on client +
        # staff + start + end, products on salon + name + sku +
        # barcode (the writer's fallbacks).
        for model in (Appointment, Product, Client, StaffMember,
                      Service):
            obj = model.objects.get()
            obj.external_id = ""
            obj.save()
        data["appointments"][0]["external_id"] = ""
        data["appointments"][0]["client_external_id"] = ""
        data["appointments"][0]["staff_member_external_id"] = ""
        data["appointments"][0]["service_external_id"] = ""
        data["products"][0]["external_id"] = ""
        data["clients"][0]["external_id"] = ""
        data["staff_members"][0]["external_id"] = ""
        data["services"][0]["external_id"] = ""
        reports = self.run_dry(data)
        for section in SLICE3:
            self.assertEqual(
                reports[section]["import_preview"]["would_unchanged"],
                1, section)

    def test_off_book_appointment_without_service_would_create(self):
        data = _data()
        data["appointments"][0]["service_id"] = None
        data["appointments"][0]["service_external_id"] = None
        data["appointments"][0]["service_name"] = "Off-book Service"
        reports = self.run_dry(data)
        preview = reports["appointments"]["import_preview"]
        self.assertEqual(
            (preview["would_create"], preview["would_skip"]), (1, 0))

    def test_dry_run_writes_nothing_explicit(self):
        self.store_matching()
        before = self.counts()
        data = _data()
        data["appointments"][0]["status"] = "confirmed"  # would-update
        data["products"][0]["price"] = "30.00"  # would-update
        data["appointment_notes"].append(
            {"id": 92, "appointment_id": 70, "body": "Brand new note.",
             "author_name": "Front Desk"})  # would-create
        self.run_dry(data)
        self.assertEqual(self.counts(), before)
        self.assertEqual(Appointment.objects.get().status, "booked")
        self.assertEqual(
            Product.objects.get().price, Decimal("25.00"))
