"""import_salon_data --dry-run slice-6 preview (cycle 146).

Slice-6 sections (stock_movements, price_changes, reminder_sends,
campaigns, campaign_sends, staff_notifications) gain the same
read-only import_preview as slices 1-5, mirroring the writer's
identity rules. Price changes, reminder sends and campaign sends
are get_or_create in the writer, and a stock movement's
update_or_create carries empty defaults, so an existing row never
previews as would-update there. Writer never entered in dry-run.
"""
import io
import json
import tempfile
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.core.management import call_command
from django.db.models.query import QuerySet as PlainQuerySet
from django.test import TestCase

from bookings.models import Appointment
from catalog.models import Product, StockMovement
from clients.models import Client
from messaging.models import Campaign, CampaignSend, ReminderSend
from saloncore.models import (
    PriceChange, Salon, Service, ServiceCategory, ServicePrice, StaffLevel)
from saloncore.test_import_salon_data import _minimal_data
from team.models import StaffMember, StaffNotification

SLICE6 = ("stock_movements", "price_changes", "reminder_sends",
          "campaigns", "campaign_sends", "staff_notifications")
MODELS = (StockMovement, PriceChange, ReminderSend, Campaign,
          CampaignSend, StaffNotification)


def _dt(hour, minute=0):
    return datetime(2026, 11, 2, hour, minute, tzinfo=dt_timezone.utc)


def _data():
    data = _minimal_data()
    data["products"] = [
        {"id": 90, "salon_id": 1, "external_id": "prod-1",
         "name": "Shampoo", "sku": "SKU-1", "barcode": "111",
         "price": "24.50", "active": True}]
    data["stock_movements"] = [
        {"id": 300, "product_id": 90, "product_external_id": "prod-1",
         "kind": "receive", "quantity_delta": 10, "note": "Delivery",
         "created_at": "2026-11-02T09:00:00+00:00"}]
    data["price_changes"] = [
        {"id": 301, "service_price_id": 40, "service_id": 20,
         "service_external_id": "svc-1", "staff_level_id": 30,
         "old_amount": "80.00", "new_amount": "85.00", "changed_by": "Ada",
         "note": "Raise", "changed_at": "2026-11-01T10:00:00+00:00"}]
    data["reminder_sends"] = [
        {"id": 302, "appointment_id": 70, "client_id": 50, "channel": "email",
         "status": "sent", "detail": "", "sent_at": "2026-11-02T13:00:00+00:00"}]
    data["campaigns"] = [
        {"id": 303, "salon_id": 1, "name": "November Offer", "channel": "email",
         "subject": "Hello", "body": "Body", "status": "sent",
         "sent_at": "2026-11-02T12:00:00+00:00",
         "created_at": "2026-11-02T11:00:00+00:00"}]
    data["campaign_sends"] = [
        {"id": 304, "campaign_id": 303, "client_id": 50, "channel": "email",
         "status": "sent", "detail": "", "sent_at": "2026-11-02T12:05:00+00:00"}]
    data["staff_notifications"] = [
        {"id": 305, "staff_member_id": 60, "kind": "arrived",
         "staff_member_external_id": "staff-1", "appointment_id": 70,
         "appointment_external_id": "appt-1", "seen_at": None,
         "created_at": "2026-11-02T14:01:00+00:00"}]
    return data


class ImportSalonDataPreviewSlice6Tests(TestCase):
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
            name="Single Process", service_minutes=45, active=True)
        price = ServicePrice.objects.create(
            service=service, staff_level=level, amount=Decimal("85.00"),
            is_from=True, active=True)
        product = Product.objects.create(
            salon=salon, external_id="prod-1", name="Shampoo",
            sku="SKU-1", barcode="111", price=Decimal("24.50"),
            active=True)
        client = Client.objects.create(
            salon=salon, external_id="cli-1", first_name="Ada",
            last_name="Optin", active=True)
        staff = StaffMember.objects.create(
            salon=salon, external_id="staff-1", staff_level=level,
            display_name="Stylist One", online_bookable=True,
            active=True)
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=service,
            external_id="appt-1", start=_dt(14), end=_dt(14, 45),
            status="booked", origin="phone")
        movement = StockMovement.objects.create(
            product=product, kind="receive", quantity_delta=10,
            note="Delivery")
        StockMovement.objects.filter(pk=movement.pk).update(created_at=_dt(9))
        change = PriceChange.objects.create(
            service_price=price, old_amount=Decimal("80.00"),
            new_amount=Decimal("85.00"), changed_by="Ada", note="Raise")
        PlainQuerySet(model=PriceChange, using="default").filter(
            pk=change.pk).update(changed_at=datetime(
                2026, 11, 1, 10, tzinfo=dt_timezone.utc))
        ReminderSend.objects.create(
            appointment=appt, client=client, channel="email",
            status="sent", sent_at=_dt(13), detail="")
        campaign = Campaign.objects.create(
            salon=salon, name="November Offer", channel="email",
            subject="Hello", body="Body", status="sent", sent_at=_dt(12))
        Campaign.objects.filter(pk=campaign.pk).update(created_at=_dt(11))
        CampaignSend.objects.create(
            campaign=campaign, client=client, channel="email",
            status="sent", sent_at=_dt(12, 5), detail="")
        note = StaffNotification.objects.create(
            staff_member=staff, appointment=appt, kind="arrived")
        StaffNotification.objects.filter(pk=note.pk).update(created_at=_dt(14, 1))

    def test_would_create_all_slice6_on_empty_db(self):
        reports = self.run_dry(_data())
        for section in SLICE6:
            preview = reports[section]["import_preview"]
            self.assertEqual(
                (preview["total"], preview["would_create"],
                 preview["would_update"], preview["would_unchanged"],
                 preview["would_skip"]), (1, 1, 0, 0, 0), section)
            self.assertEqual(preview["skipped_rows"], [], section)

    def test_would_unchanged_against_matching_stored(self):
        self.store_matching()
        reports = self.run_dry(_data())
        for section in SLICE6:
            preview = reports[section]["import_preview"]
            self.assertEqual(preview["would_unchanged"], 1, section)
            self.assertEqual(preview["would_create"], 0, section)

    def test_would_update_only_where_writer_updates(self):
        self.store_matching()
        data = _data()
        data["campaigns"][0]["subject"] = "New subject"
        data["staff_notifications"][0]["seen_at"] = (
            "2026-11-02T15:00:00+00:00")
        data["stock_movements"][0]["quantity_delta"] = 11
        data["price_changes"][0]["new_amount"] = "86.00"
        data["reminder_sends"][0]["detail"] = "changed"
        data["campaign_sends"][0]["detail"] = "changed"
        reports = self.run_dry(data)
        for section in ("campaigns", "staff_notifications"):
            self.assertEqual(
                reports[section]["import_preview"]["would_update"],
                1, section)
        # quantity_delta / new_amount are part of those rows'
        # identity: a different value is a new row, not an update.
        for section in ("stock_movements", "price_changes"):
            preview = reports[section]["import_preview"]
            self.assertEqual(
                (preview["would_create"], preview["would_update"]),
                (1, 0), section)
        # Send detail is a creation-only default on get_or_create
        # rows: an existing send is returned untouched.
        for section in ("reminder_sends", "campaign_sends"):
            preview = reports[section]["import_preview"]
            self.assertEqual(
                (preview["would_update"], preview["would_unchanged"]),
                (0, 1), section)

    def test_repeat_row_in_file_judged_against_first_row(self):
        data = _data()
        for section, new_id in (("stock_movements", 310),
                                ("price_changes", 311),
                                ("reminder_sends", 312),
                                ("campaign_sends", 314)):
            data[section].append(dict(data[section][0], id=new_id))
        data["campaigns"].append(dict(
            data["campaigns"][0], id=313, subject="Second subject"))
        data["staff_notifications"].append(dict(
            data["staff_notifications"][0], id=315,
            seen_at="2026-11-02T15:00:00+00:00"))
        reports = self.run_dry(data)
        for section in ("stock_movements", "price_changes",
                        "reminder_sends", "campaign_sends"):
            preview = reports[section]["import_preview"]
            self.assertEqual(
                (preview["would_create"], preview["would_unchanged"]),
                (1, 1), section)
        for section in ("campaigns", "staff_notifications"):
            preview = reports[section]["import_preview"]
            self.assertEqual(
                (preview["would_create"], preview["would_update"]),
                (1, 1), section)

    def test_dry_run_writes_nothing_explicit(self):
        self.store_matching()
        before = self.counts()
        data = _data()
        data["campaigns"][0]["subject"] = "Changed"  # would-update
        data["stock_movements"].append(
            {"id": 316, "product_id": 90, "kind": "sale",
             "product_external_id": "prod-1", "quantity_delta": -1,
             "note": "", "created_at": "2026-11-02T16:00:00+00:00"})
        self.run_dry(data)
        self.assertEqual(self.counts(), before)
        self.assertEqual(Campaign.objects.get().subject, "Hello")
