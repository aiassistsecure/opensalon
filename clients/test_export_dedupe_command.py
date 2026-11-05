"""Tests for the export_dedupe_candidates management command.

Synthetic fixtures only — no real salon/client data. The command is
a thin wrapper around
``clients.dedupe_export.export_duplicate_candidates_csv``; these
tests verify stdout/file output matches that service verbatim and
that salon scoping and invalid input handling apply. Duplicate
candidates are clients sharing a normalized email or phone.
"""
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from clients.dedupe_export import (
    export_duplicate_candidates,
    export_duplicate_candidates_csv,
)
from clients.models import Client
from saloncore.models import Salon


class ExportDedupeCandidatesCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")

    def _client(self, salon, first_name, last_name, **kwargs):
        return Client.objects.create(
            salon=salon, first_name=first_name, last_name=last_name, **kwargs
        )

    def _duplicates(self, salon):
        self._client(salon, "Amy", "Smith", email="amy@example.com")
        self._client(salon, "Amelia", "Smith", email="Amy@Example.com")

    def test_stdout_matches_service_output(self):
        self._duplicates(self.salon)
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(
            out.getvalue(), export_duplicate_candidates_csv(self.salon)
        )
        self.assertIn("amy@example.com", out.getvalue())

    def test_output_file_matches_service_output(self):
        self._duplicates(self.salon)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", salon_id=self.salon.id,
            output=path, stdout=out,
        )
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(
            data, export_duplicate_candidates_csv(self.salon)
        )
        self.assertEqual(out.getvalue(), "")

    def test_salon_scoping_excludes_other_salons(self):
        self._duplicates(self.salon)
        self._client(self.other_salon, "Bob", "Adams",
                     email="bob@example.com")
        self._client(self.other_salon, "Robert", "Adams",
                     email="Bob@Example.com")
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", salon_id=self.salon.id, stdout=out
        )
        text = out.getvalue()
        self.assertIn("Amy", text)
        self.assertNotIn("Bob", text)
        self.assertNotIn("bob@example.com", text)

    def test_empty_book_exports_header_only(self):
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(
            out.getvalue(), export_duplicate_candidates_csv(self.salon)
        )

    def test_key_type_email_matches_service_output(self):
        self._duplicates(self.salon)
        # Phone-only duplicates in the same salon are excluded.
        self._client(self.salon, "Bob", "Adams", phone="555-0102")
        self._client(self.salon, "Robert", "Adams",
                     phone="(555) 0102")
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", salon_id=self.salon.id,
            key_type="email", stdout=out,
        )
        self.assertEqual(
            out.getvalue(),
            export_duplicate_candidates_csv(
                self.salon, key_type="email"))
        self.assertIn("amy@example.com", out.getvalue())
        self.assertNotIn("phone", out.getvalue())
        self.assertNotIn("Bob", out.getvalue())

    def test_key_type_phone_matches_service_output(self):
        self._duplicates(self.salon)
        self._client(self.salon, "Bob", "Adams", phone="555-0102")
        self._client(self.salon, "Robert", "Adams",
                     phone="(555) 0102")
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", salon_id=self.salon.id,
            key_type="phone", stdout=out,
        )
        self.assertEqual(
            out.getvalue(),
            export_duplicate_candidates_csv(
                self.salon, key_type="phone"))
        self.assertIn("phone", out.getvalue())
        self.assertNotIn("amy@example.com", out.getvalue())

    def test_key_type_omitted_is_unfiltered(self):
        self._duplicates(self.salon)
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", salon_id=self.salon.id,
            stdout=out,
        )
        self.assertEqual(
            out.getvalue(), export_duplicate_candidates_csv(self.salon))

    def test_default_and_explicit_csv_match_service(self):
        self._duplicates(self.salon)
        want = export_duplicate_candidates_csv(self.salon)
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", salon_id=self.salon.id, stdout=out
        )
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", salon_id=self.salon.id,
            format="csv", stdout=out,
        )
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", "--salon-id", str(self.salon.id),
            "--format", "csv", stdout=out,
        )
        self.assertEqual(out.getvalue(), want)

    def test_json_output_parses_and_equals_dict_service_rows(self):
        self._duplicates(self.salon)
        rows = export_duplicate_candidates(self.salon)
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", salon_id=self.salon.id,
            format="json", stdout=out,
        )
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(
            out.getvalue(),
            json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")
        parsed = json.loads(out.getvalue())
        self.assertIsInstance(parsed[0]["client_id"], int)

    def test_json_flag_matches_dict_service(self):
        self._duplicates(self.salon)
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", "--salon-id", str(self.salon.id),
            "--format", "json", stdout=out,
        )
        self.assertEqual(
            json.loads(out.getvalue()),
            export_duplicate_candidates(self.salon))

    def test_json_composes_with_key_type_and_salon(self):
        self._duplicates(self.salon)
        self._client(self.salon, "Bob", "Adams", phone="555-0102")
        self._client(self.salon, "Robert", "Adams", phone="(555) 0102")
        self._client(self.other_salon, "Bob", "Adams",
                     email="bob@example.com")
        self._client(self.other_salon, "Robert", "Adams",
                     email="Bob@Example.com")
        rows = export_duplicate_candidates(self.salon, key_type="email")
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", salon_id=self.salon.id,
            key_type="email", format="json", stdout=out,
        )
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertIn("amy@example.com", out.getvalue())
        self.assertNotIn("phone", out.getvalue())
        self.assertNotIn("Bob", out.getvalue())

    def test_json_empty_book_is_empty_list(self):
        out = io.StringIO()
        call_command(
            "export_dedupe_candidates", salon_id=self.salon.id,
            format="json", stdout=out,
        )
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(out.getvalue(), "[]\n")

    def test_json_output_file_matches_dict_service(self):
        self._duplicates(self.salon)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dedupe.json")
            call_command(
                "export_dedupe_candidates", salon_id=self.salon.id,
                format="json", output=path, stdout=out,
            )
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written), export_duplicate_candidates(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_dedupe_candidates", salon_id=self.salon.id,
                format="xml", stdout=io.StringIO(),
            )
        with self.assertRaises(CommandError):
            call_command(
                "export_dedupe_candidates", "--salon-id", str(self.salon.id),
                "--format", "xml", stdout=io.StringIO(),
            )

    def test_unknown_salon_id_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_dedupe_candidates", salon_id=999999,
                stdout=io.StringIO(),
            )

    def test_unwritable_output_raises(self):
        self._duplicates(self.salon)
        with self.assertRaises(CommandError):
            call_command(
                "export_dedupe_candidates", salon_id=self.salon.id,
                output="/nonexistent-dir/out.csv", stdout=io.StringIO(),
            )
