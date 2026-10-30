import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase

from bookings.models import Appointment, AppointmentNote
from bookings.notes import add_note, list_notes
from clients.models import Client, ClientNote
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc


def at(hour, minute=0):
    return datetime.datetime(2026, 11, 2, hour, minute, tzinfo=UTC)


class NotesBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        self.appointment = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(10), end=at(10, 45),
        )
        self.other_appointment = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(13), end=at(13, 45),
        )


class AddNoteTests(NotesBase):
    def test_add_note_creates_appointment_note_with_author(self):
        note = add_note(self.appointment, "Prefers quiet room", author="Front Desk")
        self.assertEqual(note.appointment, self.appointment)
        self.assertEqual(note.body, "Prefers quiet room")
        self.assertEqual(note.author_name, "Front Desk")
        self.assertEqual(AppointmentNote.objects.count(), 1)

    def test_add_note_author_defaults_blank(self):
        note = add_note(self.appointment, "No author given")
        self.assertEqual(note.author_name, "")

    def test_add_note_empty_text_rejected(self):
        for text in ("", "   "):
            with self.assertRaises(ValidationError):
                add_note(self.appointment, text)
        self.assertEqual(AppointmentNote.objects.count(), 0)


class ListNotesTests(NotesBase):
    def test_list_notes_newest_first(self):
        add_note(self.appointment, "First written")
        add_note(self.appointment, "Second written")
        add_note(self.appointment, "Third written")
        bodies = [n.body for n in list_notes(self.appointment)]
        self.assertEqual(
            bodies, ["Third written", "Second written", "First written"]
        )

    def test_list_notes_only_this_appointment(self):
        add_note(self.appointment, "For this appointment")
        add_note(self.other_appointment, "For the other appointment")
        bodies = [n.body for n in list_notes(self.appointment)]
        self.assertEqual(bodies, ["For this appointment"])

    def test_list_notes_empty_when_none(self):
        self.assertEqual(list(list_notes(self.appointment)), [])


class NoteKindsNeverBlurTests(NotesBase):
    def test_appointment_notes_never_in_client_record_notes(self):
        add_note(self.appointment, "Appointment-only secret", author="Desk")
        # Not on the client's persistent record, in either direction:
        self.assertEqual(ClientNote.objects.count(), 0)
        self.assertEqual(self.client.notes.count(), 0)
        self.assertFalse(
            ClientNote.objects.filter(body="Appointment-only secret").exists()
        )

    def test_client_record_notes_never_in_appointment_notes(self):
        ClientNote.objects.create(
            client=self.client, body="Persistent allergy record",
            author_name="Desk",
        )
        add_note(self.appointment, "This visit only")
        bodies = [n.body for n in list_notes(self.appointment)]
        self.assertEqual(bodies, ["This visit only"])
        self.assertEqual(AppointmentNote.objects.count(), 1)
        self.assertFalse(
            AppointmentNote.objects.filter(
                body="Persistent allergy record"
            ).exists()
        )
        # And the record note is still intact on the client profile.
        self.assertEqual(
            [n.body for n in self.client.notes.all()],
            ["Persistent allergy record"],
        )
