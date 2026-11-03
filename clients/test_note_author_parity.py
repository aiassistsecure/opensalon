"""Parity tests: ClientNote ``author_name`` in both standalone exports.

Audit-124 rank 2: the salon_data bundle (and the bookings
appointment-note twin) carry ``ClientNote.author_name``, but both
clients standalone note surfaces omitted it. These tests prove
``clients.note_export`` and ``clients.note_search_export`` now
render the field, in dict and CSV form, with exactly the bundle's
value for the same note -- the bundle row is read once here and
every surface is compared against that one source dict.
"""
import csv
import io
import json
import tempfile

from django.core.management import call_command
from django.test import TestCase

from clients.models import Client, ClientNote
from clients.note_export import NOTE_FIELDNAMES, export_notes, export_notes_csv
from clients.note_search_export import (
    NOTE_SEARCH_FIELDNAMES,
    export_note_search_results,
    export_note_search_results_csv,
)
from saloncore.models import Salon


class NoteAuthorParityTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Amy", last_name="Smith",
            external_id="ext-1")
        self.authored = ClientNote.objects.create(
            client=self.client, body="Prefers quiet room",
            author_name="Front Desk")
        self.anonymous = ClientNote.objects.create(
            client=self.client, body="Walk-in note")

    def bundle_note(self, note):
        """Return this note's row from the salon_data bundle dict."""
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        call_command("export_salon_data", fh.name, stdout=io.StringIO())
        with open(fh.name, encoding="utf-8") as exported:
            data = json.load(exported)
        rows = [r for r in data["client_notes"] if r["id"] == note.pk]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_fieldnames_include_author_name_in_both_surfaces(self):
        self.assertIn("author_name", NOTE_FIELDNAMES)
        self.assertIn("author_name", NOTE_SEARCH_FIELDNAMES)
        self.assertEqual(NOTE_SEARCH_FIELDNAMES, NOTE_FIELDNAMES)

    def test_note_export_author_matches_bundle(self):
        for note in (self.authored, self.anonymous):
            bundle = self.bundle_note(note)
            self.assertIn("author_name", bundle)
            records = {r["note_id"]: r for r in export_notes(self.salon)}
            self.assertEqual(
                records[note.pk]["author_name"], bundle["author_name"])
            parsed = {int(r["note_id"]): r for r in csv.DictReader(
                io.StringIO(export_notes_csv(self.salon)))}
            self.assertEqual(
                parsed[note.pk]["author_name"], bundle["author_name"])

    def test_note_search_export_author_matches_bundle(self):
        bundle = self.bundle_note(self.authored)
        self.assertEqual(bundle["author_name"], "Front Desk")
        for query in ("quiet", ""):
            records = export_note_search_results(self.salon, query)
            by_id = {r["note_id"]: r for r in records}
            self.assertEqual(
                by_id[self.authored.pk]["author_name"],
                bundle["author_name"])
            parsed = {int(r["note_id"]): r for r in csv.DictReader(
                io.StringIO(export_note_search_results_csv(
                    self.salon, query)))}
            self.assertEqual(
                parsed[self.authored.pk]["author_name"],
                bundle["author_name"])

    def test_blank_author_matches_bundle_in_both_surfaces(self):
        bundle = self.bundle_note(self.anonymous)
        self.assertEqual(bundle["author_name"], "")
        record = {r["note_id"]: r for r in export_notes(self.salon)}
        self.assertEqual(
            record[self.anonymous.pk]["author_name"], bundle["author_name"])
        found = {r["note_id"]: r
                 for r in export_note_search_results(self.salon, "Walk-in")}
        self.assertEqual(
            found[self.anonymous.pk]["author_name"], bundle["author_name"])
