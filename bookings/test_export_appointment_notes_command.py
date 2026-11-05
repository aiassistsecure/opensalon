import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command

from bookings.note_export import (
    export_appointment_notes,
    export_appointment_notes_csv,
)
from bookings.test_note_search import SearchAppointmentNotesTests


class ExportAppointmentNotesCommandTests(SearchAppointmentNotesTests):
    def test_stdout_matches_service(self):
        self.make_note(self.appt, "Prefers quiet room", author="Desk")
        self.make_note(self.appt, "Allergic to latex")
        out = io.StringIO()
        call_command("export_appointment_notes",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(
            out.getvalue(), export_appointment_notes_csv(self.salon))

    def test_date_range_passed_through(self):
        when = datetime.datetime(2026, 10, 21, 12, 0,
                                 tzinfo=datetime.timezone.utc)
        self.make_note(self.appt, "in range", when=when)
        self.make_note(
            self.appt, "out of range",
            when=when + datetime.timedelta(days=10))
        out = io.StringIO()
        call_command("export_appointment_notes", salon_id=self.salon.id,
                     date_from=datetime.date(2026, 10, 21),
                     date_to=datetime.date(2026, 10, 21), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_appointment_notes_csv(
                self.salon, datetime.date(2026, 10, 21),
                datetime.date(2026, 10, 21)))
        self.assertIn("in range", out.getvalue())
        self.assertNotIn("out of range", out.getvalue())

    def test_output_file_matches_service(self):
        self.make_note(self.appt, "Prefers quiet room")
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False,
                encoding="utf-8") as fh:
            path = fh.name
        call_command("export_appointment_notes", salon_id=self.salon.id,
                     output=path, stdout=io.StringIO())
        with open(path, encoding="utf-8", newline="") as fh:
            data = fh.read()
        self.assertEqual(data, export_appointment_notes_csv(self.salon))

    def test_salon_scoping(self):
        self.make_note(self.appt, "shared keyword mine")
        self.make_note(self.other_appt, "shared keyword theirs")
        out = io.StringIO()
        call_command("export_appointment_notes",
                     salon_id=self.salon.id, stdout=out)
        self.assertIn("mine", out.getvalue())
        self.assertNotIn("theirs", out.getvalue())

    def test_appointment_id_filters_to_one_appointment(self):
        second = self._appt(self.salon, "Bob", "Adams", "Stylist Three")
        self.make_note(self.appt, "first appt note")
        self.make_note(second, "second appt note")
        out = io.StringIO()
        call_command("export_appointment_notes",
                     salon_id=self.salon.id,
                     appointment_id=self.appt.id, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_appointment_notes_csv(
                self.salon, appointment=self.appt))
        self.assertIn("first appt note", out.getvalue())
        self.assertNotIn("second appt note", out.getvalue())

    def test_appointment_id_with_date_range(self):
        when = datetime.datetime(2026, 10, 21, 12, 0,
                                 tzinfo=datetime.timezone.utc)
        self.make_note(self.appt, "in range", when=when)
        self.make_note(
            self.appt, "out of range",
            when=when + datetime.timedelta(days=10))
        out = io.StringIO()
        call_command("export_appointment_notes", salon_id=self.salon.id,
                     appointment_id=self.appt.id,
                     date_from=datetime.date(2026, 10, 21),
                     date_to=datetime.date(2026, 10, 21), stdout=out)
        self.assertIn("in range", out.getvalue())
        self.assertNotIn("out of range", out.getvalue())

    def test_unknown_appointment_id_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_appointment_notes",
                         salon_id=self.salon.id, appointment_id=999999,
                         stdout=io.StringIO())

    def test_appointment_from_other_salon_raises(self):
        self.make_note(self.other_appt, "theirs")
        with self.assertRaises(CommandError):
            call_command("export_appointment_notes",
                         salon_id=self.salon.id,
                         appointment_id=self.other_appt.id,
                         stdout=io.StringIO())

    def test_no_appointment_id_is_default_behaviour(self):
        self.make_note(self.appt, "Prefers quiet room")
        out = io.StringIO()
        call_command("export_appointment_notes",
                     salon_id=self.salon.id, appointment_id=None,
                     stdout=out)
        self.assertEqual(
            out.getvalue(), export_appointment_notes_csv(self.salon))

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_appointment_notes", salon_id=999999,
                         stdout=io.StringIO())

    def test_salon_id_required(self):
        with self.assertRaises(CommandError):
            call_command("export_appointment_notes", stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        self.make_note(self.appt, "Prefers quiet room")
        with self.assertRaises(CommandError):
            call_command("export_appointment_notes",
                         salon_id=self.salon.id,
                         output="/nonexistent-dir/out.csv",
                         stdout=io.StringIO())


class ExportAppointmentNotesFormatCommandTests(
        SearchAppointmentNotesTests):
    def test_default_format_is_csv_byte_identical(self):
        self.make_note(self.appt, "Prefers quiet room", author="Desk")
        out = io.StringIO()
        call_command("export_appointment_notes",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(
            out.getvalue(), export_appointment_notes_csv(self.salon))

    def test_explicit_csv_matches_service(self):
        self.make_note(self.appt, "Prefers quiet room")
        out = io.StringIO()
        call_command("export_appointment_notes",
                     salon_id=self.salon.id, format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(), export_appointment_notes_csv(self.salon))
        out = io.StringIO()
        call_command("export_appointment_notes",
                     "--salon-id", str(self.salon.id),
                     "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(), export_appointment_notes_csv(self.salon))

    def test_json_parses_and_equals_dict_service_rows(self):
        self.make_note(self.appt, "Prefers quiet room", author="Desk")
        self.make_note(self.appt, "Allergic to latex")
        out = io.StringIO()
        call_command("export_appointment_notes",
                     salon_id=self.salon.id, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_appointment_notes(self.salon))
        out = io.StringIO()
        call_command("export_appointment_notes",
                     "--salon-id", str(self.salon.id),
                     "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_appointment_notes(self.salon))

    def test_json_appointment_and_date_filters_compose(self):
        when = datetime.datetime(2026, 10, 21, 12, 0,
                                 tzinfo=datetime.timezone.utc)
        second = self._appt(self.salon, "Bob", "Adams", "Stylist Three")
        self.make_note(self.appt, "in range", when=when)
        self.make_note(
            self.appt, "out of range",
            when=when + datetime.timedelta(days=10))
        self.make_note(second, "second appt note", when=when)
        out = io.StringIO()
        call_command("export_appointment_notes", salon_id=self.salon.id,
                     appointment_id=self.appt.id, format="json",
                     date_from=datetime.date(2026, 10, 21),
                     date_to=datetime.date(2026, 10, 21), stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_appointment_notes(
                self.salon, datetime.date(2026, 10, 21),
                datetime.date(2026, 10, 21), appointment=self.appt))
        self.assertIn("in range", out.getvalue())
        self.assertNotIn("out of range", out.getvalue())
        self.assertNotIn("second appt note", out.getvalue())

    def test_json_output_file_matches_dict_service(self):
        self.make_note(self.appt, "Prefers quiet room")
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes.json")
            call_command("export_appointment_notes",
                         salon_id=self.salon.id, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written), export_appointment_notes(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_appointment_notes",
                         salon_id=self.salon.id, format="xml",
                         stdout=io.StringIO())
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_appointment_notes",
                         "--salon-id", str(self.salon.id),
                         "--format", "xml", stdout=io.StringIO())
