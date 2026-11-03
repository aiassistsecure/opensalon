"""import_salon_data --dry-run slice-2 preview (cycle 143).

Slice-2 sections (clients, client_notes, staff_members,
staff_services) gain the same read-only import_preview as
slice 1: would-create / would-update / would-unchanged /
would-skip counts mirroring the writer's identity rules.
Writer never entered in dry-run.
"""
import io
import json
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from clients.models import Client, ClientNote
from saloncore.management.commands.import_salon_data import SECTIONS
from saloncore.models import (
    Salon, Service, ServiceCategory, ServicePrice, StaffLevel)
from saloncore.test_import_salon_data import _minimal_data
from team.models import StaffMember, StaffService

SLICE2 = ("clients", "client_notes", "staff_members", "staff_services")
MODELS = (Client, ClientNote, StaffMember, StaffService)


def _data():
    data = _minimal_data()
    data["client_notes"] = [
        {"id": 90, "client_id": 50, "body": "Prefers quiet.",
         "author_name": "Front Desk",
         "created_at": "2026-01-01T09:00:00+00:00"}]
    data["staff_services"] = [
        {"id": 95, "staff_member_id": 60,
         "staff_member_external_id": "staff-1", "service_id": 20,
         "service_external_id": "svc-1", "enabled": True}]
    return data


class ImportSalonDataPreviewSlice2Tests(TestCase):
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
        ClientNote.objects.create(
            client=client, body="Prefers quiet.",
            author_name="Front Desk")
        staff = StaffMember.objects.create(
            salon=salon, external_id="staff-1",
            display_name="Stylist One", staff_level=level,
            online_bookable=True, active=True, pin="", email="")
        StaffService.objects.create(
            staff_member=staff, service=service, enabled=True)
        return salon

    def test_preview_present_on_slice2_sections(self):
        reports = self.run_dry(_data())
        self.assertEqual(set(reports), set(SECTIONS))
        for section in SLICE2:
            self.assertIn("import_preview", reports[section], section)

    def test_would_create_all_slice2_on_empty_db(self):
        reports = self.run_dry(_data())
        for section in SLICE2:
            preview = reports[section]["import_preview"]
            self.assertEqual(
                (preview["total"], preview["would_create"],
                 preview["would_update"], preview["would_unchanged"],
                 preview["would_skip"]), (1, 1, 0, 0, 0), section)
            self.assertEqual(preview["skipped_rows"], [], section)

    def test_would_unchanged_against_matching_stored(self):
        self.store_matching()
        reports = self.run_dry(_data())
        for section in SLICE2:
            preview = reports[section]["import_preview"]
            self.assertEqual(preview["would_unchanged"], 1, section)
            self.assertEqual(preview["would_create"], 0, section)

    def test_would_update_when_stored_fields_differ(self):
        self.store_matching()
        data = _data()
        data["clients"][0]["email_opt_in"] = True
        data["staff_members"][0]["pin"] = "1234"
        data["staff_services"][0]["enabled"] = False
        reports = self.run_dry(data)
        for section in ("clients", "staff_members", "staff_services"):
            self.assertEqual(
                reports[section]["import_preview"]["would_update"],
                1, section)
        # A note's body is its identity: a changed body is a
        # new note, never an update (writer defaults are empty).
        self.assertEqual(
            reports["client_notes"]["import_preview"]["would_unchanged"],
            1)

    def test_repeat_row_in_file_judged_against_first_row(self):
        data = _data()
        data["clients"].append(dict(data["clients"][0], id=51))
        data["staff_services"].append(
            dict(data["staff_services"][0], id=96, enabled=False))
        reports = self.run_dry(data)
        client = reports["clients"]["import_preview"]
        self.assertEqual(
            (client["would_create"], client["would_unchanged"]), (1, 1))
        link = reports["staff_services"]["import_preview"]
        self.assertEqual(
            (link["would_create"], link["would_update"]), (1, 1))

    def test_no_external_id_identities_match_stored(self):
        self.store_matching()
        data = _data()
        # Drop the external ids: clients key on salon+name+email+
        # phone, staff on salon+display_name (writer's fallbacks).
        stored_client = Client.objects.get()
        stored_client.external_id = ""
        stored_client.save()
        stored_staff = StaffMember.objects.get()
        stored_staff.external_id = ""
        stored_staff.save()
        data["clients"][0]["external_id"] = ""
        data["staff_members"][0]["external_id"] = ""
        data["staff_services"][0]["staff_member_external_id"] = ""
        data["appointments"][0]["client_external_id"] = ""
        data["appointments"][0]["staff_member_external_id"] = ""
        reports = self.run_dry(data)
        for section in ("clients", "staff_members", "staff_services"):
            self.assertEqual(
                reports[section]["import_preview"]["would_unchanged"],
                1, section)

    def test_dry_run_writes_nothing_explicit(self):
        self.store_matching()
        before = self.counts()
        data = _data()
        data["clients"][0]["email_opt_in"] = True  # would-update
        data["staff_services"][0]["enabled"] = False  # would-update
        data["client_notes"].append(
            {"id": 91, "client_id": 50, "body": "Brand new note.",
             "author_name": "Front Desk"})  # would-create
        self.run_dry(data)
        self.assertEqual(self.counts(), before)
        self.assertFalse(Client.objects.get().email_opt_in)
        self.assertTrue(StaffService.objects.get().enabled)
