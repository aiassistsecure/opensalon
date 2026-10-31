import datetime
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment, AppointmentNote
from clients.models import Client, ClientNote
from clients.note_search import search_client_notes
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc


class SearchClientNotesTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.amy = Client.objects.create(
            salon=self.salon, first_name="Amy", last_name="Smith"
        )
        self.bob = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Adams"
        )

    def make_note(self, client, body, when=None):
        note = ClientNote.objects.create(client=client, body=body)
        if when is not None:
            ClientNote.objects.filter(pk=note.pk).update(created_at=when)
            note.created_at = when
        return note

    def results(self, query, salon=None):
        return list(search_client_notes(salon or self.salon, query))

    def test_case_insensitive_substring(self):
        note = self.make_note(self.amy, "Prefers QUIET room")
        self.assertEqual(self.results("quiet"), [note])
        self.assertEqual(self.results("QUIET"), [note])
        self.assertEqual(self.results("uie"), [note])
        self.assertEqual(self.results("loud"), [])

    def test_returns_note_with_client(self):
        note = self.make_note(self.amy, "Allergic to latex")
        found = self.results("latex")
        self.assertEqual(found, [note])
        self.assertEqual(found[0].client, self.amy)
        qs = search_client_notes(self.salon, "latex")
        self.assertEqual(qs.model, ClientNote)

    def test_newest_first_with_id_tiebreak(self):
        base = timezone.now() - timedelta(days=10)
        old = self.make_note(self.amy, "match old", base)
        new = self.make_note(self.bob, "match new", base + timedelta(days=2))
        same_a = self.make_note(self.amy, "match same A", base + timedelta(days=1))
        same_b = self.make_note(self.amy, "match same B", base + timedelta(days=1))
        self.assertEqual(
            self.results("match"), [new, same_b, same_a, old]
        )

    def test_salon_isolation(self):
        mine = self.make_note(self.amy, "shared keyword mine")
        other_client = Client.objects.create(
            salon=self.other, first_name="Amy", last_name="Smith"
        )
        self.make_note(other_client, "shared keyword theirs")
        self.assertEqual(self.results("shared keyword"), [mine])
        self.assertEqual(len(self.results("shared", salon=self.other)), 1)

    def test_empty_query_returns_all_salon_notes_newest_first(self):
        base = timezone.now() - timedelta(days=5)
        first = self.make_note(self.amy, "one", base)
        second = self.make_note(self.bob, "two", base + timedelta(days=1))
        expected = [second, first]
        self.assertEqual(self.results(""), expected)
        self.assertEqual(self.results("   "), expected)
        self.assertEqual(self.results(None), expected)

    def test_appointment_notes_never_appear(self):
        record = self.make_note(self.amy, "violet toner formula")
        staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair"
        )
        service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        start = datetime.datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
        appt = Appointment.objects.create(
            client=self.amy, staff_member=staff, service=service,
            start=start, end=start + timedelta(minutes=45),
        )
        AppointmentNote.objects.create(
            appointment=appt, body="violet toner appointment-only"
        )
        AppointmentNote.objects.create(
            appointment=appt, body="appointment-only unique phrase"
        )
        self.assertEqual(AppointmentNote.objects.count(), 2)
        # Matching text in an appointment note does not surface it;
        # only the persistent record note is returned.
        self.assertEqual(self.results("violet toner"), [record])
        # A phrase that exists ONLY as an appointment note finds nothing.
        self.assertEqual(self.results("unique phrase"), [])
        self.assertEqual(self.results("appointment-only"), [])

    def test_read_only(self):
        self.make_note(self.amy, "A note")
        before = (Client.objects.count(), ClientNote.objects.count())
        self.results("note")
        self.assertEqual(
            (Client.objects.count(), ClientNote.objects.count()), before
        )
