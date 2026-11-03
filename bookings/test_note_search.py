import datetime
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment, AppointmentNote
from bookings.note_search import search_appointment_notes
from clients.models import Client, ClientNote
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc


class SearchAppointmentNotesTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.appt = self._appt(self.salon, "Amy", "Smith", "Stylist One")
        self.other_appt = self._appt(self.other, "Amy", "Smith", "Stylist Two")

    def _appt(self, salon, first, last, staff_name):
        client = Client.objects.create(
            salon=salon, first_name=first, last_name=last)
        staff = StaffMember.objects.create(salon=salon, display_name=staff_name)
        cat = ServiceCategory.objects.create(salon=salon, name="Hair")
        svc = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        start = datetime.datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
        return Appointment.objects.create(
            client=client, staff_member=staff, service=svc,
            start=start, end=start + timedelta(minutes=45))

    def make_note(self, appt, body, author="", when=None):
        note = AppointmentNote.objects.create(
            appointment=appt, body=body, author_name=author)
        if when is not None:
            AppointmentNote.objects.filter(pk=note.pk).update(created_at=when)
            note.created_at = when
        return note

    def results(self, query, salon=None):
        return list(search_appointment_notes(salon or self.salon, query))

    def test_body_case_insensitive_substring(self):
        note = self.make_note(self.appt, "Prefers QUIET room")
        self.assertEqual(self.results("quiet"), [note])
        self.assertEqual(self.results("uie"), [note])
        self.assertEqual(self.results("loud"), [])

    def test_author_search(self):
        note = self.make_note(self.appt, "A note", author="Front Desk")
        self.make_note(self.appt, "Other", author="Manager")
        self.assertEqual(self.results("front desk"), [note])
        self.assertEqual(self.results("FRONT"), [note])

    def test_newest_first_with_id_tiebreak(self):
        base = timezone.now() - timedelta(days=10)
        old = self.make_note(self.appt, "match old", when=base)
        new = self.make_note(self.appt, "match new", when=base + timedelta(days=2))
        a = self.make_note(self.appt, "match A", when=base + timedelta(days=1))
        b = self.make_note(self.appt, "match B", when=base + timedelta(days=1))
        self.assertEqual(self.results("match"), [new, b, a, old])

    def test_salon_isolation(self):
        mine = self.make_note(self.appt, "shared keyword mine")
        self.make_note(self.other_appt, "shared keyword theirs")
        self.assertEqual(self.results("shared keyword"), [mine])

    def test_empty_query_returns_all_newest_first(self):
        base = timezone.now() - timedelta(days=5)
        first = self.make_note(self.appt, "one", when=base)
        second = self.make_note(self.appt, "two", when=base + timedelta(days=1))
        for q in ("", "   ", None):
            self.assertEqual(self.results(q), [second, first])

    def test_client_record_notes_never_appear(self):
        note = self.make_note(self.appt, "violet toner appointment")
        ClientNote.objects.create(
            client=self.appt.client, body="violet toner record")
        self.assertEqual(self.results("violet toner"), [note])
        self.assertEqual(self.results("record"), [])

    def test_read_only(self):
        self.make_note(self.appt, "A note")
        before = AppointmentNote.objects.count()
        self.results("note")
        self.assertEqual(AppointmentNote.objects.count(), before)
