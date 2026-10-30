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
