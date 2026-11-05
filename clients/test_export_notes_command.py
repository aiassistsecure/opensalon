"""Tests for the export_notes management command.

Synthetic fixtures only — no real salon/client data. The command is
a thin wrapper around ``clients.note_export.export_notes_csv``;
these tests verify stdout/file output matches that service verbatim
and that salon scoping and invalid input handling apply.
"""
import io
import json
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client, ClientNote
from clients.note_export import export_notes, export_notes_csv
from saloncore.models import Salon


class ExportNotesCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")

    def _client_with_note(self, salon, first_name, last_name, body):
        client = Client.objects.create(
            salon=salon, first_name=first_name, last_name=last_name
        )
        ClientNote.objects.create(client=client, body=body)
        return client

    def test_stdout_matches_service_output(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        self._client_with_note(self.salon, "Bob", "Adams", "Allergic to latex")
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(out.getvalue(), export_notes_csv(self.salon))

    def test_output_file_matches_service_output(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        self._client_with_note(self.salon, "Bob", "Adams", "Allergic to latex")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id,
            output=path, stdout=out,
        )
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(data, export_notes_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_salon_scoping_excludes_other_salons(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        self._client_with_note(
            self.other_salon, "Bob", "Adams", "Allergic to latex"
        )
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id, stdout=out
        )
        text = out.getvalue()
        self.assertIn("Amy", text)
        self.assertNotIn("Bob", text)
        self.assertNotIn("Allergic to latex", text)

    def test_empty_book_exports_header_only(self):
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(out.getvalue(), export_notes_csv(self.salon))

    def test_unknown_salon_id_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_notes", salon_id=999999, stdout=io.StringIO()
            )

    def test_salon_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command("export_notes", stdout=io.StringIO())

    def test_client_id_filters_to_one_client(self):
        amy = self._client_with_note(
            self.salon, "Amy", "Smith", "Prefers quiet room")
        self._client_with_note(self.salon, "Bob", "Adams", "Allergic")
        ClientNote.objects.create(client=amy, body="Second Amy note")
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id,
            client_id=amy.id, stdout=out,
        )
        self.assertEqual(
            out.getvalue(), export_notes_csv(self.salon, client=amy))
        self.assertIn("Prefers quiet room", out.getvalue())
        self.assertIn("Second Amy note", out.getvalue())
        self.assertNotIn("Bob", out.getvalue())
        self.assertNotIn("Allergic", out.getvalue())

    def test_no_client_id_is_salon_wide_default(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Amy note")
        self._client_with_note(self.salon, "Bob", "Adams", "Bob note")
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(out.getvalue(), export_notes_csv(self.salon))
        self.assertEqual(
            out.getvalue(),
            export_notes_csv(self.salon, client=None))

    def test_unknown_client_id_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_notes", salon_id=self.salon.id,
                client_id=999999, stdout=io.StringIO(),
            )

    def test_client_from_other_salon_raises(self):
        theirs = self._client_with_note(
            self.other_salon, "Bob", "Adams", "Allergic to latex")
        with self.assertRaises(CommandError):
            call_command(
                "export_notes", salon_id=self.salon.id,
                client_id=theirs.id, stdout=io.StringIO(),
            )

    def _dated_note(self, salon, first_name, last_name, body, when):
        client = Client.objects.create(
            salon=salon, first_name=first_name, last_name=last_name
        )
        note = ClientNote.objects.create(client=client, body=body)
        ClientNote.objects.filter(pk=note.pk).update(created_at=when)
        return client

    def test_start_and_end_date_window(self):
        import datetime
        from django.utils import timezone
        base = timezone.now() - datetime.timedelta(days=10)
        self._dated_note(self.salon, "Amy", "Smith", "Early note", base)
        self._dated_note(
            self.salon, "Bob", "Adams", "Late note",
            base + datetime.timedelta(days=5))
        start = (base + datetime.timedelta(days=2)).date().isoformat()
        end = (base + datetime.timedelta(days=6)).date().isoformat()
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id,
            start_date=start, end_date=end, stdout=out,
        )
        self.assertEqual(
            out.getvalue(),
            export_notes_csv(
                self.salon,
                start=(base + datetime.timedelta(days=2)).date(),
                end=(base + datetime.timedelta(days=6)).date()))
        self.assertIn("Late note", out.getvalue())
        self.assertNotIn("Early note", out.getvalue())

    def test_start_date_only(self):
        import datetime
        from django.utils import timezone
        base = timezone.now() - datetime.timedelta(days=10)
        self._dated_note(self.salon, "Amy", "Smith", "Early note", base)
        self._dated_note(
            self.salon, "Bob", "Adams", "Late note",
            base + datetime.timedelta(days=5))
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id,
            start_date=(base + datetime.timedelta(days=2)).date(),
            stdout=out,
        )
        self.assertIn("Late note", out.getvalue())
        self.assertNotIn("Early note", out.getvalue())

    def test_window_composes_with_client_id(self):
        import datetime
        from django.utils import timezone
        base = timezone.now() - datetime.timedelta(days=10)
        amy = self._dated_note(
            self.salon, "Amy", "Smith", "Amy early", base)
        ClientNote.objects.create(client=amy, body="Amy late placeholder")
        late = ClientNote.objects.filter(
            client=amy, body="Amy late placeholder").get()
        ClientNote.objects.filter(pk=late.pk).update(
            created_at=base + datetime.timedelta(days=5))
        self._dated_note(
            self.salon, "Bob", "Adams", "Bob late",
            base + datetime.timedelta(days=5))
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id, client_id=amy.id,
            start_date=(base + datetime.timedelta(days=2)).date().isoformat(),
            stdout=out,
        )
        self.assertIn("Amy late placeholder", out.getvalue())
        self.assertNotIn("Amy early", out.getvalue())
        self.assertNotIn("Bob late", out.getvalue())

    def test_invalid_start_date_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_notes", salon_id=self.salon.id,
                start_date="not-a-date", stdout=io.StringIO(),
            )

    def test_unwritable_output_raises(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        with self.assertRaises(CommandError):
            call_command(
                "export_notes", salon_id=self.salon.id,
                output="/nonexistent-dir/out.csv", stdout=io.StringIO(),
            )

    def test_default_format_is_csv_byte_identical(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        out = io.StringIO()
        call_command("export_notes", salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(), export_notes_csv(self.salon))

    def test_explicit_csv_format_matches_service(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id,
            format="csv", stdout=out)
        self.assertEqual(out.getvalue(), export_notes_csv(self.salon))

    def test_csv_flag_matches_service(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        out = io.StringIO()
        call_command(
            "export_notes", "--salon-id", str(self.salon.id),
            "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), export_notes_csv(self.salon))

    def test_json_output_parses_and_equals_dict_service_rows(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        self._client_with_note(self.salon, "Bob", "Adams", "Allergic to latex")
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id,
            format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()), export_notes(self.salon))

    def test_json_flag_matches_dict_service(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        out = io.StringIO()
        call_command(
            "export_notes", "--salon-id", str(self.salon.id),
            "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()), export_notes(self.salon))
        self.assertIn("Prefers quiet room", out.getvalue())

    def test_json_empty_book_exports_empty_list(self):
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id,
            format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])

    def test_json_output_file_matches_dict_service(self):
        self._client_with_note(self.salon, "Amy", "Smith", "Prefers quiet room")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id,
            format="json", output=path, stdout=out)
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(json.loads(data), export_notes(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_json_client_id_filter_composes(self):
        amy = self._client_with_note(
            self.salon, "Amy", "Smith", "Prefers quiet room")
        self._client_with_note(self.salon, "Bob", "Adams", "Allergic")
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id,
            client_id=amy.id, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_notes(self.salon, client=amy))
        self.assertNotIn("Bob", out.getvalue())

    def test_json_date_window_composes(self):
        import datetime
        from django.utils import timezone
        base = timezone.now() - datetime.timedelta(days=10)
        self._dated_note(self.salon, "Amy", "Smith", "Early note", base)
        self._dated_note(
            self.salon, "Bob", "Adams", "Late note",
            base + datetime.timedelta(days=5))
        start = (base + datetime.timedelta(days=2)).date()
        end = (base + datetime.timedelta(days=6)).date()
        out = io.StringIO()
        call_command(
            "export_notes", salon_id=self.salon.id,
            start_date=start.isoformat(), end_date=end.isoformat(),
            format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_notes(self.salon, start=start, end=end))
        self.assertIn("Late note", out.getvalue())
        self.assertNotIn("Early note", out.getvalue())

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_notes", salon_id=self.salon.id,
                format="xml", stdout=io.StringIO())

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(
                "export_notes", "--salon-id", str(self.salon.id),
                "--format", "xml", stdout=io.StringIO())
