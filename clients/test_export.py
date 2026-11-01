import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from clients.export import export_client
from clients.models import Client, ClientNote
from saloncore.models import Salon


class ExportClientTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.client = Client.objects.create(
            salon=self.salon,
            external_id="ext-42",
            first_name="Amy",
            last_name="Smith",
            email="amy@example.com",
            phone="555-0101",
            sms_opt_in=True,
            email_opt_in=False,
        )

    def test_all_fields_present(self):
        data = export_client(self.client)
        self.assertEqual(data["id"], self.client.id)
        self.assertEqual(data["salon_id"], self.salon.id)
        self.assertEqual(data["external_id"], "ext-42")
        self.assertEqual(data["first_name"], "Amy")
        self.assertEqual(data["last_name"], "Smith")
        self.assertEqual(data["email"], "amy@example.com")
        self.assertEqual(data["phone"], "555-0101")
        self.assertTrue(data["active"])
        self.assertIsNotNone(data["created_at"])
        self.assertIn("notes", data)

    def test_opt_ins_faithfully_reflected(self):
        data = export_client(self.client)
        self.assertTrue(data["sms_opt_in"])
        self.assertFalse(data["email_opt_in"])
        # Flipped combination must also be reported exactly as stored.
        self.client.sms_opt_in = False
        self.client.email_opt_in = True
        self.client.save()
        self.client.refresh_from_db()
        data = export_client(self.client)
        self.assertFalse(data["sms_opt_in"])
        self.assertTrue(data["email_opt_in"])

    def test_record_notes_included_in_chronological_order(self):
        older = ClientNote.objects.create(
            client=self.client, body="Older note", author_name="Front Desk"
        )
        newer = ClientNote.objects.create(
            client=self.client, body="Newer note", author_name="Stylist"
        )
        # Force distinct timestamps so chronological order is unambiguous
        # regardless of the model's default newest-first ordering.
        base = timezone.now() - timedelta(days=2)
        ClientNote.objects.filter(pk=older.pk).update(created_at=base)
        ClientNote.objects.filter(pk=newer.pk).update(
            created_at=base + timedelta(days=1)
        )
        data = export_client(self.client)
        self.assertEqual(
            [n["body"] for n in data["notes"]], ["Older note", "Newer note"]
        )
        self.assertEqual(data["notes"][0]["id"], older.id)
        self.assertEqual(data["notes"][0]["client_id"], self.client.id)
        self.assertEqual(data["notes"][0]["author_name"], "Front Desk")
        self.assertEqual(data["notes"][1]["author_name"], "Stylist")

    def test_client_with_no_notes_exports_empty_list(self):
        data = export_client(self.client)
        self.assertEqual(data["notes"], [])

    def test_datetimes_serialized_as_iso_strings(self):
        ClientNote.objects.create(client=self.client, body="A note")
        data = export_client(self.client)
        self.assertIsInstance(data["created_at"], str)
        self.assertEqual(data["created_at"], self.client.created_at.isoformat())
        self.assertIsInstance(data["notes"][0]["created_at"], str)
        # The whole dict must round-trip through JSON unchanged.
        self.assertEqual(json.loads(json.dumps(data)), data)

    def test_appointment_notes_are_not_included(self):
        # Appointment-only notes belong to bookings and must never
        # leak into a client record export. Guard by field shape:
        # exported notes carry only the ClientNote fields.
        ClientNote.objects.create(client=self.client, body="Record note")
        data = export_client(self.client)
        self.assertEqual(len(data["notes"]), 1)
        self.assertEqual(
            set(data["notes"][0]),
            {"id", "client_id", "body", "author_name", "created_at"},
        )

    def test_payload_included_when_present(self):
        payload = {"clientId": "ext-42", "extraUnmappedField": "kept-me",
                   "nested": {"flags": ["a", "b"]}}
        self.client.payload = payload
        self.client.save()
        self.client.refresh_from_db()
        data = export_client(self.client)
        self.assertEqual(data["payload"], payload)
        self.assertEqual(json.loads(json.dumps(data)), data)

    def test_payload_omitted_when_absent(self):
        # setUp client was created without a payload (default empty).
        data = export_client(self.client)
        self.assertNotIn("payload", data)
        self.assertEqual(json.loads(json.dumps(data)), data)

    def test_other_clients_notes_not_included(self):
        other = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Adams"
        )
        ClientNote.objects.create(client=other, body="Someone else's note")
        data = export_client(self.client)
        self.assertEqual(data["notes"], [])
