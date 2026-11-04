import csv
import datetime
import io
import json
from datetime import timedelta

from django.utils import timezone

from bookings.models import AppointmentNote
from bookings.note_export import (
    NOTE_FIELDNAMES,
    export_appointment_notes,
    export_appointment_notes_csv,
)
from bookings.test_note_search import SearchAppointmentNotesTests
from clients.models import ClientNote


class AppointmentNoteExportTests(SearchAppointmentNotesTests):
    def test_fieldnames_and_header(self):
        self.assertEqual(
            NOTE_FIELDNAMES,
            ["appointment_id", "note_id", "author_name", "body",
             "created_at"],
        )
        rows = list(csv.reader(
            io.StringIO(export_appointment_notes_csv(self.salon))))
        self.assertEqual(rows, [NOTE_FIELDNAMES])

    def test_rows_exact_verbatim(self):
        when = timezone.now() - timedelta(days=1)
        note = self.make_note(
            self.appt, "Allergic to X, use gloves", author="Desk",
            when=when)
        records = export_appointment_notes(self.salon)
        self.assertEqual(records, [{
            "appointment_id": self.appt.pk,
            "note_id": note.pk,
            "author_name": "Desk",
            "body": "Allergic to X, use gloves",
            "created_at": when.isoformat(),
        }])
        self.assertEqual(json.loads(json.dumps(records)), records)

    def test_ordering_by_appointment_then_created_at_then_id(self):
        base = timezone.now() - timedelta(days=10)
        other_appt_note = self.make_note(
            self.appt, "only appt note", when=base)
        # A second appointment in the same salon sorts after by id
        # regardless of its note's earlier timestamp.
        second = self._appt(self.salon, "Bob", "Adams", "Stylist Three")
        early = self.make_note(second, "second appt early",
                               when=base - timedelta(days=5))
        late = self.make_note(second, "second appt late",
                              when=base + timedelta(days=1))
        records = export_appointment_notes(self.salon)
        self.assertEqual(
            [r["note_id"] for r in records],
            [other_appt_note.pk, early.pk, late.pk],
        )

    def test_salon_isolation(self):
        mine = self.make_note(self.appt, "Mine")
        self.make_note(self.other_appt, "Theirs")
        records = export_appointment_notes(self.salon)
        self.assertEqual([r["note_id"] for r in records], [mine.pk])
        self.assertNotIn("Theirs",
                         export_appointment_notes_csv(self.salon))
        self.assertEqual(export_appointment_notes(None), [])

    def test_client_record_notes_never_leak_in(self):
        self.make_note(self.appt, "Appointment-only note")
        ClientNote.objects.create(
            client=self.appt.client, body="Persistent record secret")
        records = export_appointment_notes(self.salon)
        self.assertEqual([r["body"] for r in records],
                         ["Appointment-only note"])
        self.assertNotIn("Persistent record secret",
                         export_appointment_notes_csv(self.salon))

    def test_date_range_inclusive_on_created_at(self):
        base = datetime.datetime(2026, 10, 20, 12, 0,
                                 tzinfo=datetime.timezone.utc)
        before = self.make_note(self.appt, "before", when=base)
        first_day = self.make_note(
            self.appt, "first day",
            when=base + timedelta(days=1, hours=1))
        last_day = self.make_note(
            self.appt, "last day",
            when=base + timedelta(days=3, hours=-1))
        self.make_note(self.appt, "after",
                       when=base + timedelta(days=5))
        day = datetime.date(2026, 10, 21)
        records = export_appointment_notes(
            self.salon, day, datetime.date(2026, 10, 23))
        self.assertEqual([r["note_id"] for r in records],
                         [first_day.pk, last_day.pk])
        # Single bound defaults to a single-day range.
        single = export_appointment_notes(self.salon, day)
        self.assertEqual([r["note_id"] for r in single], [first_day.pk])
        to_only = export_appointment_notes(
            self.salon, date_to=datetime.date(2026, 10, 23))
        self.assertEqual([r["note_id"] for r in to_only], [last_day.pk])
        self.assertNotIn(before.pk, [r["note_id"] for r in records])

    def test_reversed_range_and_empty(self):
        self.make_note(self.appt, "A note")
        self.assertEqual(
            export_appointment_notes(
                self.salon, datetime.date(2026, 10, 23),
                datetime.date(2026, 10, 21)),
            [],
        )
        self.assertEqual(
            export_appointment_notes_csv(self.other),
            ",".join(NOTE_FIELDNAMES) + "\n",
        )

    def test_csv_matches_list_export(self):
        self.make_note(self.appt, "One, with comma", author="Desk")
        self.make_note(self.appt, "Two")
        parsed = list(csv.DictReader(io.StringIO(
            export_appointment_notes_csv(self.salon))))
        records = export_appointment_notes(self.salon)
        self.assertEqual(len(parsed), len(records))
        for row, record in zip(parsed, records):
            self.assertEqual(int(row["note_id"]), record["note_id"])
            self.assertEqual(int(row["appointment_id"]),
                             record["appointment_id"])
            self.assertEqual(row["body"], record["body"])
            self.assertEqual(row["author_name"], record["author_name"])
            self.assertEqual(row["created_at"], record["created_at"])

    def test_read_only(self):
        self.make_note(self.appt, "A note")
        before = AppointmentNote.objects.count()
        export_appointment_notes(self.salon)
        export_appointment_notes_csv(self.salon)
        self.assertEqual(AppointmentNote.objects.count(), before)

    def test_appointment_filter_default_none_is_unchanged(self):
        second = self._appt(self.salon, "Bob", "Adams", "Stylist Three")
        self.make_note(self.appt, "first appt note")
        self.make_note(second, "second appt note")
        default = export_appointment_notes(self.salon)
        self.assertEqual(
            export_appointment_notes(self.salon, appointment=None),
            default)
        self.assertEqual(len(default), 2)
        self.assertEqual(
            export_appointment_notes_csv(self.salon, appointment=None),
            export_appointment_notes_csv(self.salon))

    def test_appointment_filter_only_that_appointment(self):
        second = self._appt(self.salon, "Bob", "Adams", "Stylist Three")
        mine = self.make_note(self.appt, "first appt note")
        self.make_note(second, "second appt note")
        records = export_appointment_notes(
            self.salon, appointment=self.appt)
        self.assertEqual([r["note_id"] for r in records], [mine.pk])
        csv_text = export_appointment_notes_csv(
            self.salon, appointment=self.appt)
        self.assertIn("first appt note", csv_text)
        self.assertNotIn("second appt note", csv_text)
        other_records = export_appointment_notes(
            self.salon, appointment=second)
        self.assertEqual(
            [r["body"] for r in other_records], ["second appt note"])

    def test_appointment_filter_date_window_still_applies(self):
        base = datetime.datetime(2026, 10, 20, 12, 0,
                                 tzinfo=datetime.timezone.utc)
        in_window = self.make_note(
            self.appt, "in window", when=base + timedelta(days=1))
        self.make_note(
            self.appt, "out of window", when=base + timedelta(days=5))
        second = self._appt(self.salon, "Bob", "Adams", "Stylist Three")
        self.make_note(
            second, "other appt in window",
            when=base + timedelta(days=1))
        records = export_appointment_notes(
            self.salon, datetime.date(2026, 10, 21),
            datetime.date(2026, 10, 21), appointment=self.appt)
        self.assertEqual([r["note_id"] for r in records], [in_window.pk])

    def test_appointment_filter_other_salon_appointment_is_empty(self):
        self.make_note(self.appt, "Mine")
        self.make_note(self.other_appt, "Theirs")
        self.assertEqual(
            export_appointment_notes(
                self.salon, appointment=self.other_appt),
            [])
        self.assertEqual(
            export_appointment_notes_csv(
                self.salon, appointment=self.other_appt),
            ",".join(NOTE_FIELDNAMES) + "\n")
