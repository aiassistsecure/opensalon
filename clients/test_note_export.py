import csv
import datetime
import io
import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment, AppointmentNote
from clients.models import Client, ClientNote
from clients.note_export import (
    NOTE_FIELDNAMES,
    export_notes,
    export_notes_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc


class NoteExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def make_client(self, first, last, salon=None, **kw):
        return Client.objects.create(
            salon=salon or self.salon, first_name=first, last_name=last, **kw
        )

    def make_note(self, client, body, when=None):
        note = ClientNote.objects.create(client=client, body=body)
        if when is not None:
            ClientNote.objects.filter(pk=note.pk).update(created_at=when)
            note.created_at = when
        return note

    def test_fieldnames_and_header(self):
        self.assertEqual(
            NOTE_FIELDNAMES,
            ["client_external_id", "client_first_name",
             "client_last_name", "note_id", "created_at", "body"],
        )
        rows = list(csv.reader(io.StringIO(export_notes_csv(self.salon))))
        self.assertEqual(rows, [NOTE_FIELDNAMES])

    def test_no_contact_details_beyond_name(self):
        client = self.make_client(
            "Amy", "Smith", external_id="ext-1",
            email="amy@example.com", phone="555-0101",
        )
        self.make_note(client, "Prefers quiet room")
        records = export_notes(self.salon)
        self.assertEqual(len(records), 1)
        self.assertNotIn("email", records[0])
        self.assertNotIn("phone", records[0])
        self.assertNotIn("amy@example.com", export_notes_csv(self.salon))
        self.assertNotIn("555-0101", export_notes_csv(self.salon))

    def test_rows_exact(self):
        client = self.make_client("Amy", "Smith", external_id="ext-42")
        when = timezone.now() - timedelta(days=1)
        note = self.make_note(client, "Allergic to X", when=when)
        records = export_notes(self.salon)
        self.assertEqual(records, [{
            "client_external_id": "ext-42",
            "client_first_name": "Amy",
            "client_last_name": "Smith",
            "note_id": note.pk,
            "created_at": when.isoformat(),
            "body": "Allergic to X",
        }])
        self.assertEqual(json.loads(json.dumps(records)), records)

    def test_ordering_by_client_then_created_at_then_id(self):
        base = timezone.now() - timedelta(days=10)
        bob = self.make_client("Bob", "Adams")
        amy = self.make_client("Amy", "Smith")
        # Created out of order on purpose; export must re-sort.
        amy_late = self.make_note(amy, "Amy late", base + timedelta(days=2))
        bob_note = self.make_note(bob, "Bob note", base + timedelta(days=5))
        amy_early = self.make_note(amy, "Amy early", base)
        amy_same_a = self.make_note(amy, "Amy same A", base + timedelta(days=1))
        amy_same_b = self.make_note(amy, "Amy same B", base + timedelta(days=1))
        records = export_notes(self.salon)
        # Client order first (Adams before Smith), then created_at,
        # then note id as the tie-break for equal timestamps.
        self.assertEqual(
            [r["note_id"] for r in records],
            [bob_note.pk, amy_early.pk, amy_same_a.pk,
             amy_same_b.pk, amy_late.pk],
        )

    def test_salon_isolation(self):
        mine = self.make_client("Amy", "Smith")
        theirs = self.make_client("Bob", "Adams", salon=self.other)
        self.make_note(mine, "Mine")
        self.make_note(theirs, "Theirs")
        records = export_notes(self.salon)
        self.assertEqual([r["body"] for r in records], ["Mine"])
        self.assertEqual(
            [r["body"] for r in export_notes(self.other)], ["Theirs"]
        )
        self.assertNotIn("Theirs", export_notes_csv(self.salon))

    def test_appointment_notes_never_leak_in(self):
        client = self.make_client("Amy", "Smith", external_id="ext-7")
        self.make_note(client, "Persistent record note")
        staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        start = datetime.datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=service,
            start=start, end=start + timedelta(minutes=45),
        )
        AppointmentNote.objects.create(
            appointment=appt, body="Appointment-only secret"
        )
        self.assertEqual(AppointmentNote.objects.count(), 1)
        records = export_notes(self.salon)
        self.assertEqual([r["body"] for r in records],
                         ["Persistent record note"])
        self.assertNotIn("Appointment-only secret",
                         export_notes_csv(self.salon))

    def test_csv_matches_list_export(self):
        client = self.make_client("Amy", "Smith", external_id="ext-9")
        self.make_note(client, "One, with comma")
        self.make_note(client, "Two")
        parsed = list(csv.DictReader(io.StringIO(export_notes_csv(self.salon))))
        records = export_notes(self.salon)
        self.assertEqual(len(parsed), len(records))
        for row, record in zip(parsed, records):
            self.assertEqual(int(row["note_id"]), record["note_id"])
            self.assertEqual(row["body"], record["body"])
            self.assertEqual(row["created_at"], record["created_at"])
            self.assertEqual(
                row["client_external_id"], record["client_external_id"])

    def test_empty(self):
        self.make_client("Amy", "Smith")  # client with no notes
        self.assertEqual(export_notes(self.salon), [])
        self.assertEqual(
            export_notes_csv(self.salon),
            ",".join(NOTE_FIELDNAMES) + "\n",
        )

    def test_read_only(self):
        client = self.make_client("Amy", "Smith")
        self.make_note(client, "A note")
        before = (Client.objects.count(), ClientNote.objects.count())
        export_notes(self.salon)
        export_notes_csv(self.salon)
        self.assertEqual(
            (Client.objects.count(), ClientNote.objects.count()), before)
