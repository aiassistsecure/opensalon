import json

from django.test import TestCase

from clients.export import export_client
from clients.export_all import export_all_clients
from clients.models import Client, ClientNote
from saloncore.models import Salon


class ExportAllClientsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def _client(self, first_name, last_name, **kwargs):
        return Client.objects.create(
            salon=self.salon, first_name=first_name, last_name=last_name, **kwargs
        )

    def test_empty_book_exports_empty_list(self):
        self.assertEqual(export_all_clients(), [])

    def test_multiple_clients_in_deterministic_order(self):
        # Created out of order; export sorts by last, then first name.
        self._client("Zoe", "Smith")
        self._client("Amy", "Smith")
        self._client("Bob", "Adams")
        data = export_all_clients()
        self.assertEqual(
            [(c["first_name"], c["last_name"]) for c in data],
            [("Bob", "Adams"), ("Amy", "Smith"), ("Zoe", "Smith")],
        )
        # Repeated calls return the identical order.
        self.assertEqual(export_all_clients(), data)

    def test_same_name_clients_tie_break_by_id(self):
        first = self._client("Amy", "Smith")
        second = self._client("Amy", "Smith")
        data = export_all_clients()
        self.assertEqual([c["id"] for c in data], [first.id, second.id])

    def test_opt_ins_preserved_per_client(self):
        self._client("Amy", "Smith", sms_opt_in=True, email_opt_in=False)
        self._client("Bob", "Adams", sms_opt_in=False, email_opt_in=True)
        self._client("Cid", "Jones")
        by_first = {c["first_name"]: c for c in export_all_clients()}
        self.assertTrue(by_first["Amy"]["sms_opt_in"])
        self.assertFalse(by_first["Amy"]["email_opt_in"])
        self.assertFalse(by_first["Bob"]["sms_opt_in"])
        self.assertTrue(by_first["Bob"]["email_opt_in"])
        self.assertFalse(by_first["Cid"]["sms_opt_in"])
        self.assertFalse(by_first["Cid"]["email_opt_in"])

    def test_note_counts(self):
        amy = self._client("Amy", "Smith")
        bob = self._client("Bob", "Adams")
        self._client("Cid", "Jones")
        ClientNote.objects.create(client=amy, body="One")
        ClientNote.objects.create(client=amy, body="Two")
        ClientNote.objects.create(client=bob, body="Only")
        by_first = {c["first_name"]: c for c in export_all_clients()}
        self.assertEqual(by_first["Amy"]["note_count"], 2)
        self.assertEqual(by_first["Bob"]["note_count"], 1)
        self.assertEqual(by_first["Cid"]["note_count"], 0)
        for record in by_first.values():
            self.assertEqual(record["note_count"], len(record["notes"]))

    def test_same_field_shape_as_single_export_plus_note_count(self):
        client = self._client(
            "Amy", "Smith", external_id="ext-1", email="amy@example.com",
            phone="555-0101", sms_opt_in=True,
        )
        ClientNote.objects.create(client=client, body="A note")
        (record,) = export_all_clients()
        single = export_client(client)
        self.assertEqual(set(record), set(single) | {"note_count"})
        for key in single:
            self.assertEqual(record[key], single[key])

    def test_no_appointment_data_and_json_serializable(self):
        self._client("Amy", "Smith")
        data = export_all_clients()
        for record in data:
            self.assertNotIn("appointments", record)
            self.assertNotIn("appointment_notes", record)
        self.assertEqual(json.loads(json.dumps(data)), data)

    def test_optional_salon_filter(self):
        other_salon = Salon.objects.create(name="Other Salon")
        self._client("Amy", "Smith")
        Client.objects.create(
            salon=other_salon, first_name="Bob", last_name="Adams"
        )
        self.assertEqual(len(export_all_clients()), 2)
        scoped = export_all_clients(salon=self.salon)
        self.assertEqual([c["first_name"] for c in scoped], ["Amy"])
