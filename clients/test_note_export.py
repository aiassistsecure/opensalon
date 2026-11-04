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
             "client_last_name", "note_id", "created_at", "author_name",
             "body"],
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
            "author_name": "",
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

    def test_default_output_byte_identical(self):
        # Hard-coded expected bytes for the salon-wide export: the
        # default (and an explicit client=None) must match exactly.
        amy = self.make_client("Amy", "Smith", external_id="ext-1")
        bob = self.make_client("Bob", "Adams", external_id="ext-2")
        base = timezone.now() - timedelta(days=3)
        bob_note = self.make_note(bob, "Bob note", when=base)
        amy_note = self.make_note(
            amy, "Amy note", when=base + timedelta(days=1))
        expected_records = [
            {"client_external_id": "ext-2",
             "client_first_name": "Bob", "client_last_name": "Adams",
             "note_id": bob_note.pk,
             "created_at": base.isoformat(), "author_name": "",
             "body": "Bob note"},
            {"client_external_id": "ext-1",
             "client_first_name": "Amy", "client_last_name": "Smith",
             "note_id": amy_note.pk,
             "created_at": (base + timedelta(days=1)).isoformat(),
             "author_name": "", "body": "Amy note"},
        ]
        expected_csv = (
            ",".join(NOTE_FIELDNAMES) + "\n"
            f"ext-2,Bob,Adams,{bob_note.pk},{base.isoformat()},,Bob note\n"
            f"ext-1,Amy,Smith,{amy_note.pk},"
            f"{(base + timedelta(days=1)).isoformat()},,Amy note\n"
        )
        self.assertEqual(export_notes(self.salon), expected_records)
        self.assertEqual(
            export_notes(self.salon, client=None), expected_records)
        self.assertEqual(export_notes_csv(self.salon), expected_csv)
        self.assertEqual(
            export_notes_csv(self.salon, client=None), expected_csv)

    def test_filtered_by_client(self):
        amy = self.make_client("Amy", "Smith")
        bob = self.make_client("Bob", "Adams")
        base = timezone.now() - timedelta(days=3)
        self.make_note(bob, "Bob note", when=base)
        amy_late = self.make_note(
            amy, "Amy late", when=base + timedelta(days=2))
        amy_early = self.make_note(amy, "Amy early", when=base)
        records = export_notes(self.salon, client=amy)
        self.assertEqual(
            [r["note_id"] for r in records],
            [amy_early.pk, amy_late.pk])
        self.assertTrue(
            all(r["client_first_name"] == "Amy" for r in records))
        parsed = list(csv.DictReader(io.StringIO(
            export_notes_csv(self.salon, client=amy))))
        self.assertEqual(
            [int(r["note_id"]) for r in parsed],
            [amy_early.pk, amy_late.pk])

    def test_filtered_client_with_no_notes(self):
        amy = self.make_client("Amy", "Smith")
        bob = self.make_client("Bob", "Adams")
        self.make_note(bob, "Bob note")
        self.assertEqual(export_notes(self.salon, client=amy), [])
        self.assertEqual(
            export_notes_csv(self.salon, client=amy),
            ",".join(NOTE_FIELDNAMES) + "\n")

    def test_window_start_only(self):
        amy = self.make_client("Amy", "Smith")
        base = timezone.now() - timedelta(days=10)
        self.make_note(amy, "Early", when=base)
        late = self.make_note(amy, "Late", when=base + timedelta(days=5))
        records = export_notes(self.salon, start=base + timedelta(days=2))
        self.assertEqual([r["note_id"] for r in records], [late.pk])

    def test_window_end_only_datetime(self):
        amy = self.make_client("Amy", "Smith")
        base = timezone.now() - timedelta(days=10)
        early = self.make_note(amy, "Early", when=base)
        self.make_note(amy, "Late", when=base + timedelta(days=5))
        records = export_notes(self.salon, end=base + timedelta(days=2))
        self.assertEqual([r["note_id"] for r in records], [early.pk])

    def test_window_date_bounds_include_whole_end_day(self):
        amy = self.make_client("Amy", "Smith")
        day = datetime.date(2026, 10, 20)
        start_dt = datetime.datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
        end_dt = datetime.datetime(2026, 10, 22, 17, 30, tzinfo=UTC)
        self.make_note(amy, "Before", when=start_dt - timedelta(days=1))
        first = self.make_note(amy, "First day", when=start_dt)
        last = self.make_note(amy, "Last day", when=end_dt)
        self.make_note(amy, "After", when=end_dt + timedelta(days=1))
        records = export_notes(
            self.salon, start=day, end=day + timedelta(days=2))
        self.assertEqual(
            [r["note_id"] for r in records], [first.pk, last.pk])
        parsed = list(csv.DictReader(io.StringIO(export_notes_csv(
            self.salon, start=day, end=day + timedelta(days=2)))))
        self.assertEqual(
            [int(r["note_id"]) for r in parsed], [first.pk, last.pk])

    def test_window_start_date_end_date_aliases(self):
        amy = self.make_client("Amy", "Smith")
        base = timezone.now() - timedelta(days=10)
        self.make_note(amy, "Early", when=base)
        late = self.make_note(amy, "Late", when=base + timedelta(days=5))
        records = export_notes(
            self.salon, start_date=base + timedelta(days=2))
        self.assertEqual([r["note_id"] for r in records], [late.pk])
        self.assertEqual(
            export_notes_csv(
                self.salon, start_date=base, end_date=base),
            export_notes_csv(self.salon, start=base, end=base))

    def test_window_composes_with_client(self):
        amy = self.make_client("Amy", "Smith")
        bob = self.make_client("Bob", "Adams")
        base = timezone.now() - timedelta(days=10)
        self.make_note(amy, "Amy early", when=base)
        amy_late = self.make_note(
            amy, "Amy late", when=base + timedelta(days=5))
        self.make_note(bob, "Bob late", when=base + timedelta(days=5))
        records = export_notes(
            self.salon, client=amy, start=base + timedelta(days=2))
        self.assertEqual([r["note_id"] for r in records], [amy_late.pk])

    def test_window_no_matches(self):
        amy = self.make_client("Amy", "Smith")
        base = timezone.now() - timedelta(days=10)
        self.make_note(amy, "Early", when=base)
        self.assertEqual(
            export_notes(self.salon, start=base + timedelta(days=30)), [])
        self.assertEqual(
            export_notes_csv(self.salon, start=base + timedelta(days=30)),
            ",".join(NOTE_FIELDNAMES) + "\n")

    def test_window_default_none_byte_identical(self):
        amy = self.make_client("Amy", "Smith", external_id="ext-1")
        base = timezone.now() - timedelta(days=3)
        self.make_note(amy, "Amy note", when=base)
        self.assertEqual(
            export_notes(self.salon, start=None, end=None),
            export_notes(self.salon))
        self.assertEqual(
            export_notes_csv(self.salon, start=None, end=None),
            export_notes_csv(self.salon))

    def test_filtered_client_from_other_salon_is_empty(self):
        mine = self.make_client("Amy", "Smith")
        theirs = self.make_client("Bob", "Adams", salon=self.other)
        self.make_note(mine, "Mine")
        self.make_note(theirs, "Theirs")
        # Salon filter still applies over the client filter.
        self.assertEqual(export_notes(self.salon, client=theirs), [])
        self.assertEqual(
            export_notes_csv(self.salon, client=theirs),
            ",".join(NOTE_FIELDNAMES) + "\n")
        self.assertEqual(
            [r["body"] for r in export_notes(self.other, client=theirs)],
            ["Theirs"])
