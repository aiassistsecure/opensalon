import csv
import io
import json
from unittest import mock

from django.test import TestCase

from bookings.note_search import search_appointment_notes
from bookings.note_search_export import (
    APPOINTMENT_NOTE_SEARCH_FIELDNAMES,
    export_appointment_note_search_results,
    export_appointment_note_search_results_csv,
)
from bookings.test_note_search import SearchAppointmentNotesTests


class NoteSearchExportTests(SearchAppointmentNotesTests):
    def test_fieldnames(self):
        self.assertEqual(APPOINTMENT_NOTE_SEARCH_FIELDNAMES,
                         ["appointment_id", "note_id", "created_at",
                          "author_name", "body"])

    def test_header_only_when_no_match(self):
        self.make_note(self.appt, "Prefers quiet room")
        self.assertEqual(
            export_appointment_note_search_results(self.salon, "nope"), [])
        self.assertEqual(
            export_appointment_note_search_results_csv(self.salon, "nope"),
            ",".join(APPOINTMENT_NOTE_SEARCH_FIELDNAMES) + "\n")

    def test_rows_match_search_newest_first(self):
        old = self.make_note(self.appt, "match old", author="Desk")
        new = self.make_note(self.appt, "match new", author="Desk")
        records = export_appointment_note_search_results(self.salon, "match")
        expected_ids = [n.pk for n in search_appointment_notes(self.salon, "match")]
        self.assertEqual([r["note_id"] for r in records], expected_ids)
        self.assertEqual(records[0]["body"], "match new")
        self.assertEqual(records[0]["appointment_id"], self.appt.pk)
        self.assertEqual(records[0]["author_name"], "Desk")
        parsed = list(csv.DictReader(io.StringIO(
            export_appointment_note_search_results_csv(self.salon, "match"))))
        self.assertEqual(parsed, [
            {k: ("" if v is None else str(v)) for k, v in r.items()}
            for r in records])
        self.assertEqual(json.loads(json.dumps(records)), records)

    def test_delegates_to_search_service(self):
        with mock.patch(
            "bookings.note_search_export.search_appointment_notes",
            wraps=search_appointment_notes,
        ) as spy:
            export_appointment_note_search_results(self.salon, "quiet")
        spy.assert_called_once_with(self.salon, "quiet")

    def test_salon_isolation_and_record_notes_excluded(self):
        mine = self.make_note(self.appt, "shared keyword mine")
        self.make_note(self.other_appt, "shared keyword theirs")
        records = export_appointment_note_search_results(
            self.salon, "shared keyword")
        self.assertEqual([r["note_id"] for r in records], [mine.pk])
