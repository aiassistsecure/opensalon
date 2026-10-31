"""Regression tests: export_clients shape must round-trip via import_clients.

RT-M1 (round-trip spike, cycle 53): the importer originally read only
Phorest field names, so re-importing an OpenSalon export exited 0
while silently dropping names, phone and both opt-ins, and used the
internal numeric ``id`` as ``external_id`` (0/7,143 true external_ids
survived). Notes in the export had no importer at all (RT-M3).

Synthetic records only — no real salon/client data.
"""
import io
import json
import tempfile

from django.core.management import call_command
from django.test import TestCase

from clients.export_all import export_all_clients
from clients.models import Client, ClientNote
from saloncore.models import Salon


def _write(payload):
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fh)
    fh.close()
    return fh.name


def _import(payload, salon):
    out = io.StringIO()
    call_command("import_clients", _write(payload), salon=salon,
                 stdout=out)
    return out.getvalue()


class ExportShapeRoundTripTests(TestCase):
    def test_export_import_round_trip_preserves_every_field_and_note(self):
        source = Salon.objects.create(name="Source Salon")
        client = Client.objects.create(
            salon=source, external_id="ext-rt-1",
            first_name="Ada", last_name="Vale",
            email="ada.vale@example.com", phone="555-0142",
            email_opt_in=True, sms_opt_in=False, active=False,
        )
        ClientNote.objects.create(
            client=client, body="Prefers a quiet room",
            author_name="Front Desk")

        records = export_all_clients(salon=source)
        self.assertEqual(len(records), 1)
        # The export carries the internal id alongside external_id;
        # the importer must never confuse the two.
        self.assertEqual(records[0]["id"], client.id)
        self.assertEqual(records[0]["external_id"], "ext-rt-1")

        out = _import(records, salon="Target Salon")
        self.assertIn('"created": 1', out)
        self.assertIn('"notes_created": 1', out)

        imported = Client.objects.get(
            salon__name="Target Salon", external_id="ext-rt-1")
        self.assertEqual(imported.first_name, "Ada")
        self.assertEqual(imported.last_name, "Vale")
        self.assertEqual(imported.email, "ada.vale@example.com")
        self.assertEqual(imported.phone, "555-0142")
        self.assertTrue(imported.email_opt_in)
        self.assertFalse(imported.sms_opt_in)
        self.assertFalse(imported.active)
        notes = list(imported.notes.all())
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].body, "Prefers a quiet room")
        self.assertEqual(notes[0].author_name, "Front Desk")

    def test_reimport_is_idempotent_for_clients_and_notes(self):
        source = Salon.objects.create(name="Source Salon")
        client = Client.objects.create(
            salon=source, external_id="ext-rt-2",
            first_name="Bea", last_name="Wells",
            email="bea@example.com", phone="555-0143",
            email_opt_in=False, sms_opt_in=True, active=True,
        )
        ClientNote.objects.create(client=client, body="Allergic note",
                                  author_name="Bea")
        records = export_all_clients(salon=source)

        _import(records, salon="Target Salon")
        out = _import(records, salon="Target Salon")
        self.assertIn('"created": 0', out)
        self.assertIn('"unchanged": 1', out)
        self.assertIn('"notes_created": 0', out)
        target = Client.objects.get(
            salon__name="Target Salon", external_id="ext-rt-2")
        self.assertTrue(target.sms_opt_in)
        self.assertFalse(target.email_opt_in)
        self.assertTrue(target.active)
        self.assertEqual(target.notes.count(), 1)
        self.assertEqual(
            Client.objects.filter(salon__name="Target Salon").count(), 1)

    def test_export_shape_never_substitutes_internal_id(self):
        payload = [{
            "id": 424242, "salon_id": 9, "external_id": "ext-real-9",
            "first_name": "Cyd", "last_name": "Rey",
            "email": "cyd@example.com", "phone": "555-0144",
            "email_opt_in": True, "sms_opt_in": True, "active": True,
            "created_at": "2026-01-01T00:00:00+00:00", "notes": [],
            "note_count": 0,
        }]
        _import(payload, salon="Target Salon")
        client = Client.objects.get(external_id="ext-real-9")
        self.assertEqual(client.first_name, "Cyd")
        self.assertEqual(client.phone, "555-0144")
        self.assertFalse(
            Client.objects.filter(external_id="424242").exists())

    def test_export_shape_blank_external_id_is_skipped_not_id_keyed(self):
        payload = [{
            "id": 31337, "external_id": "",
            "first_name": "No", "last_name": "StableId",
            "email": "", "phone": "555-0145",
            "email_opt_in": False, "sms_opt_in": False, "active": True,
            "notes": [],
        }]
        out = _import(payload, salon="Target Salon")
        self.assertIn('"skipped": 1', out)
        self.assertEqual(Client.objects.count(), 0)

    def test_phorest_shape_still_imports(self):
        payload = [{
            "clientId": "cli-keep", "firstName": "Pam",
            "lastName": "Source", "email": "pam@example.com",
            "mobile": "555-0146",
            "emailMarketingConsent": True, "emailReminderConsent": True,
            "smsMarketingConsent": False, "smsReminderConsent": False,
        }]
        _import(payload, salon="Target Salon")
        client = Client.objects.get(external_id="cli-keep")
        self.assertEqual(client.first_name, "Pam")
        self.assertEqual(client.phone, "555-0146")
        self.assertTrue(client.email_opt_in)
        self.assertFalse(client.sms_opt_in)
        self.assertTrue(client.active)
