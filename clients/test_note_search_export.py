import csv
import datetime
import io
import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment, AppointmentNote
from clients.models import Client, ClientNote
from clients.note_export import NOTE_FIELDNAMES
from clients.note_search import search_client_notes
from clients.note_search_export import (
    NOTE_SEARCH_FIELDNAMES,
    export_note_search_results,
    export_note_search_results_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc


class NoteSearchExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.amy = Client.objects.create(
            salon=self.salon, first_name="Amy", last_name="Smith",
            external_id="ext-1", email="amy@example.com",
            phone="555-0101")
        self.bob = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Adams",
            external_id="ext-2")

    def make_note(self, client, body, when=None):
        note = ClientNote.objects.create(client=client, body=body)
        if when is not None:
            ClientNote.objects.filter(pk=note.pk).update(created_at=when)
            note.created_at = when
        return note

    def test_fieldnames_match_note_export(self):
        self.assertEqual(NOTE_SEARCH_FIELDNAMES, NOTE_FIELDNAMES)
        self.assertEqual(
            NOTE_SEARCH_FIELDNAMES,
            ["client_external_id", "client_first_name",
             "client_last_name", "note_id", "created_at", "author_name",
             "body"])

    def test_header_only_when_no_match(self):
        self.make_note(self.amy, "Prefers quiet room")
        self.assertEqual(
            export_note_search_results(self.salon, "no-such-text"), [])
        self.assertEqual(
            export_note_search_results_csv(self.salon, "no-such-text"),
            ",".join(NOTE_SEARCH_FIELDNAMES) + "\n")

    def test_rows_match_search_service_newest_first(self):
        base = timezone.now() - timedelta(days=10)
        old = self.make_note(self.amy, "match old", base)
        new = self.make_note(self.bob, "match new", base + timedelta(days=2))
        for query in ("match", "MATCH", ""):
            expected_ids = [
                n.pk for n in search_client_notes(self.salon, query)]
            records = export_note_search_results(self.salon, query)
            self.assertEqual([r["note_id"] for r in records], expected_ids)
        records = export_note_search_results(self.salon, "match")
        self.assertEqual(records, [
            {"client_external_id": "ext-2", "client_first_name": "Bob",
             "client_last_name": "Adams", "note_id": new.pk,
             "created_at": new.created_at.isoformat(), "author_name": "",
             "body": "match new"},
            {"client_external_id": "ext-1", "client_first_name": "Amy",
             "client_last_name": "Smith", "note_id": old.pk,
             "created_at": old.created_at.isoformat(), "author_name": "",
             "body": "match old"},
        ])
        parsed = list(csv.DictReader(io.StringIO(
            export_note_search_results_csv(self.salon, "match"))))
        self.assertEqual(parsed, [
            {k: ("" if v is None else str(v)) for k, v in r.items()}
            for r in records])
        self.assertEqual(json.loads(json.dumps(records)), records)

    def test_delegates_to_search_service(self):
        with mock.patch(
            "clients.note_search_export.search_client_notes",
            wraps=search_client_notes,
        ) as spy:
            export_note_search_results(self.salon, "quiet")
        spy.assert_called_once_with(self.salon, "quiet")

    def test_no_contact_details_beyond_name(self):
        self.make_note(self.amy, "Prefers quiet room")
        records = export_note_search_results(self.salon, "quiet")
        self.assertNotIn("email", records[0])
        self.assertNotIn("phone", records[0])
        text = export_note_search_results_csv(self.salon, "quiet")
        self.assertNotIn("amy@example.com", text)
        self.assertNotIn("555-0101", text)

    def test_salon_isolation(self):
        mine = self.make_note(self.amy, "shared keyword mine")
        other_client = Client.objects.create(
            salon=self.other, first_name="Amy", last_name="Smith")
        self.make_note(other_client, "shared keyword theirs")
        records = export_note_search_results(self.salon, "shared keyword")
        self.assertEqual([r["note_id"] for r in records], [mine.pk])
        self.assertNotIn(
            "theirs",
            export_note_search_results_csv(self.salon, "shared keyword"))

    def test_appointment_notes_never_appear(self):
        record = self.make_note(self.amy, "violet toner formula")
        staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        start = datetime.datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
        appt = Appointment.objects.create(
            client=self.amy, staff_member=staff, service=service,
            start=start, end=start + timedelta(minutes=45))
        AppointmentNote.objects.create(
            appointment=appt, body="violet toner appointment-only")
        records = export_note_search_results(self.salon, "violet toner")
        self.assertEqual([r["note_id"] for r in records], [record.pk])
        self.assertEqual(
            export_note_search_results(self.salon, "appointment-only"), [])

    def test_empty_query_returns_all(self):
        self.make_note(self.amy, "one")
        self.make_note(self.bob, "two")
        self.assertEqual(
            len(export_note_search_results(self.salon, "")), 2)
        self.assertEqual(
            len(export_note_search_results(self.salon, None)), 2)

    def test_read_only(self):
        self.make_note(self.amy, "A note")
        before = (Client.objects.count(), ClientNote.objects.count())
        export_note_search_results(self.salon, "note")
        export_note_search_results_csv(self.salon, "note")
        self.assertEqual(
            (Client.objects.count(), ClientNote.objects.count()), before)
