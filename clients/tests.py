from django.db import IntegrityError, transaction
from django.test import TestCase

from clients.models import Client, ClientNote
from saloncore.models import Salon


class ClientModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def test_creation_and_salon_fk(self):
        client = Client.objects.create(
            salon=self.salon,
            first_name="Test",
            last_name="Example",
            email="test.example@example.com",
            phone="555-0100",
        )
        self.assertEqual(client.salon, self.salon)
        self.assertIn(client, list(self.salon.clients.all()))
        self.assertTrue(client.active)
        self.assertIsNotNone(client.created_at)

    def test_opt_ins_default_false(self):
        client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        client.refresh_from_db()
        self.assertFalse(client.sms_opt_in)
        self.assertFalse(client.email_opt_in)

    def test_opt_in_true_case(self):
        client = Client.objects.create(
            salon=self.salon,
            first_name="Opted",
            last_name="In",
            sms_opt_in=True,
            email_opt_in=True,
        )
        client.refresh_from_db()
        self.assertTrue(client.sms_opt_in)
        self.assertTrue(client.email_opt_in)

    def test_str_is_first_last(self):
        client = Client(salon=self.salon, first_name="Test", last_name="Example")
        self.assertEqual(str(client), "Test Example")

    def test_ordering_by_last_then_first(self):
        Client.objects.create(
            salon=self.salon, first_name="Zoe", last_name="Smith"
        )
        Client.objects.create(
            salon=self.salon, first_name="Amy", last_name="Smith"
        )
        Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Adams"
        )
        names = list(
            Client.objects.values_list("last_name", "first_name")
        )
        self.assertEqual(
            names,
            [("Adams", "Bob"), ("Smith", "Amy"), ("Smith", "Zoe")],
        )


class ClientNoteModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )

    def test_creation_and_fk(self):
        note = ClientNote.objects.create(
            client=self.client, body="Prefers quiet appointments.", author_name="Front Desk"
        )
        self.assertEqual(note.client, self.client)
        self.assertIn(note, list(self.client.notes.all()))
        self.assertIsNotNone(note.created_at)

    def test_fk_cascade_on_client_delete(self):
        ClientNote.objects.create(client=self.client, body="Note one")
        ClientNote.objects.create(client=self.client, body="Note two")
        self.assertEqual(ClientNote.objects.count(), 2)
        self.client.delete()
        self.assertEqual(ClientNote.objects.count(), 0)

    def test_ordering_newest_first(self):
        first = ClientNote.objects.create(client=self.client, body="First note")
        second = ClientNote.objects.create(client=self.client, body="Second note")
        notes = list(ClientNote.objects.all())
        # ordering is -created_at; with equal timestamps pk order is not guaranteed,
        # so verify Meta ordering and that both notes are returned
        self.assertEqual(ClientNote._meta.ordering, ["-created_at"])
        self.assertEqual(set(notes), {first, second})
        if first.created_at != second.created_at:
            self.assertEqual(notes, [second, first])

    def test_str_short(self):
        note = ClientNote(client=self.client, body="Short note")
        s = str(note)
        self.assertIn("Short note", s)
        self.assertIn("Test Example", s)
        long_note = ClientNote(client=self.client, body="x" * 100)
        self.assertLess(len(str(long_note)), 100)

    def test_blank_author_allowed(self):
        note = ClientNote.objects.create(client=self.client, body="No author note")
        note.refresh_from_db()
        self.assertEqual(note.author_name, "")
        note2 = ClientNote.objects.create(
            client=self.client, body="Explicit blank", author_name=""
        )
        self.assertEqual(note2.author_name, "")


class StrictConstraintsTests(TestCase):
    """N-M17: StrictConstraints enforces clients Meta.constraints on save().

    NEDB DYOR §9.3/§9.4: schemaless NEDB creates no DB constraints, so
    the declared catalog is enforced in the app layer; violations
    surface as IntegrityError, as on an enforcing backend.
    """

    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example",
            external_id="client-1",
        )

    def test_duplicate_client_external_id_per_salon_rejected(self):
        duplicate = Client(
            salon=self.salon, first_name="Copy", last_name="Client",
            external_id="client-1",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                duplicate.save()
        self.assertEqual(Client.objects.filter(external_id="client-1").count(), 1)

    def test_same_external_id_in_other_salon_allowed(self):
        Client.objects.create(
            salon=self.other_salon, first_name="Other", last_name="Client",
            external_id="client-1",
        )

    def test_duplicate_blank_client_external_id_allowed(self):
        Client.objects.create(salon=self.salon, first_name="A", last_name="One")
        Client.objects.create(salon=self.salon, first_name="B", last_name="Two")

    def test_update_into_duplicate_client_external_id_rejected(self):
        other = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Client",
            external_id="client-2",
        )
        other.external_id = "client-1"
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                other.save()

    def test_legitimate_saves_and_updates_pass(self):
        self.client.first_name = "Renamed"
        self.client.save()
        self.client.save(update_fields=["first_name"])
        self.client.external_id = "client-1b"
        self.client.save(update_fields=["external_id"])
        self.client.refresh_from_db()
        self.assertEqual(self.client.external_id, "client-1b")
