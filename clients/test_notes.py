"""Tests for the clients.notes record-note service.

Mirrors bookings.test_notes: the service is the single write
path for persistent client record notes, cleans/validates the
body itself, is salon-scoped, and never blurs into appointment
notes. Fixtures are tiny synthetic records -- unit logic only.
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from bookings.models import AppointmentNote
from clients.models import Client, ClientNote
from clients.notes import add_client_note, list_client_notes
from saloncore.models import Salon


class NotesBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        self.other_client = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Example")


class AddClientNoteTests(NotesBase):
    def test_creates_note_with_author(self):
        note = add_client_note(
            self.salon, self.client, "Allergic to latex", author="Front Desk")
        self.assertEqual(note.client, self.client)
        self.assertEqual(note.body, "Allergic to latex")
        self.assertEqual(note.author_name, "Front Desk")
        self.assertEqual(ClientNote.objects.count(), 1)

    def test_author_defaults_blank(self):
        note = add_client_note(self.salon, self.client, "No author given")
        self.assertEqual(note.author_name, "")

    def test_body_and_author_are_cleaned(self):
        note = add_client_note(
            self.salon, self.client, "  Prefers quiet room  ",
            author="  Desk  ")
        self.assertEqual(note.body, "Prefers quiet room")
        self.assertEqual(note.author_name, "Desk")

    def test_empty_body_rejected(self):
        for body in ("", "   ", None, 123):
            with self.assertRaises(ValidationError):
                add_client_note(self.salon, self.client, body)
        self.assertEqual(ClientNote.objects.count(), 0)

    def test_client_from_other_salon_rejected(self):
        foreign = Client.objects.create(
            salon=self.other_salon, first_name="Out", last_name="Sider")
        with self.assertRaises(ValidationError):
            add_client_note(self.salon, foreign, "Should not land")
        self.assertEqual(ClientNote.objects.count(), 0)

    def test_unsaved_salon_or_client_rejected(self):
        with self.assertRaises(ValidationError):
            add_client_note(Salon(name="Unsaved"), self.client, "Text")
        with self.assertRaises(ValidationError):
            add_client_note(
                self.salon,
                Client(salon=self.salon, first_name="U", last_name="N"),
                "Text")
        self.assertEqual(ClientNote.objects.count(), 0)

    def test_creates_no_appointment_note(self):
        add_client_note(self.salon, self.client, "Persistent record")
        self.assertEqual(AppointmentNote.objects.count(), 0)


class ListClientNotesTests(NotesBase):
    def test_newest_first(self):
        add_client_note(self.salon, self.client, "First written")
        add_client_note(self.salon, self.client, "Second written")
        add_client_note(self.salon, self.client, "Third written")
        bodies = [n.body for n in list_client_notes(self.salon, self.client)]
        self.assertEqual(
            bodies, ["Third written", "Second written", "First written"])

    def test_only_this_client(self):
        add_client_note(self.salon, self.client, "For this client")
        add_client_note(self.salon, self.other_client, "For the other")
        bodies = [n.body for n in list_client_notes(self.salon, self.client)]
        self.assertEqual(bodies, ["For this client"])

    def test_empty_when_none(self):
        self.assertEqual(list(list_client_notes(self.salon, self.client)), [])

    def test_cross_salon_client_rejected(self):
        with self.assertRaises(ValidationError):
            list_client_notes(self.other_salon, self.client)
