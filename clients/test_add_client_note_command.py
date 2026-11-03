"""Tests for the add_client_note management command.

The command is a thin wrapper around
``clients.notes.add_client_note``: a real run creates exactly
one note on the right client, ``--dry-run`` creates none but
prints the would-be note (service validation still applied),
and unknown salon/client, salon mismatch, and empty body
surface as ``CommandError`` with nothing written. Fixtures are
tiny synthetic records -- unit logic only.
"""
import io
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import AppointmentNote
from clients.models import Client, ClientNote
from saloncore.models import Salon


class AddClientNoteCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        self.other_client = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Example")

    def test_real_run_creates_exactly_one_note_on_right_client(self):
        out = io.StringIO()
        call_command(
            "add_client_note", salon_id=self.salon.pk,
            client_id=self.client.pk, body="Prefers quiet room",
            author="Front Desk", stdout=out)
        self.assertEqual(ClientNote.objects.count(), 1)
        (note,) = ClientNote.objects.all()
        self.assertEqual(note.client, self.client)
        self.assertEqual(note.body, "Prefers quiet room")
        self.assertEqual(note.author_name, "Front Desk")
        self.assertEqual(self.other_client.notes.count(), 0)
        self.assertIn("Prefers quiet room", out.getvalue())

    def test_real_run_string_args(self):
        out = io.StringIO()
        call_command(
            "add_client_note", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk),
            "--body", "Arrive early", stdout=out)
        self.assertEqual(ClientNote.objects.count(), 1)
        (note,) = ClientNote.objects.all()
        self.assertEqual(note.author_name, "")

    def test_real_run_creates_no_appointment_note(self):
        call_command(
            "add_client_note", salon_id=self.salon.pk,
            client_id=self.client.pk, body="Persistent only",
            stdout=io.StringIO())
        self.assertEqual(AppointmentNote.objects.count(), 0)

    def test_dry_run_creates_none_but_prints_would_be_note(self):
        out = io.StringIO()
        call_command(
            "add_client_note", salon_id=self.salon.pk,
            client_id=self.client.pk, body="  Would-be note  ",
            author="Desk", dry_run=True, stdout=out)
        self.assertEqual(ClientNote.objects.count(), 0)
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn("Would-be note", text)
        self.assertIn("Desk", text)
        self.assertIn(str(self.client.pk), text)

    def test_dry_run_flag_form(self):
        out = io.StringIO()
        call_command(
            "add_client_note", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk), "--body", "Preview",
            "--dry-run", stdout=out)
        self.assertEqual(ClientNote.objects.count(), 0)
        self.assertIn("Preview", out.getvalue())

    def test_dry_run_empty_body_is_command_error_and_writes_nothing(self):
        with self.assertRaises(CommandError):
            call_command(
                "add_client_note", salon_id=self.salon.pk,
                client_id=self.client.pk, body="   ",
                dry_run=True, stdout=io.StringIO())
        self.assertEqual(ClientNote.objects.count(), 0)

    def test_empty_body_is_command_error_and_writes_nothing(self):
        for body in ("", "   "):
            with self.assertRaises(CommandError):
                call_command(
                    "add_client_note", salon_id=self.salon.pk,
                    client_id=self.client.pk, body=body,
                    stdout=io.StringIO())
        self.assertEqual(ClientNote.objects.count(), 0)

    def test_unknown_client_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "add_client_note", salon_id=self.salon.pk,
                client_id=999999, body="Hello", stdout=io.StringIO())
        self.assertEqual(ClientNote.objects.count(), 0)

    def test_unknown_salon_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "add_client_note", salon_id=999999,
                client_id=self.client.pk, body="Hello",
                stdout=io.StringIO())
        self.assertEqual(ClientNote.objects.count(), 0)

    def test_client_outside_salon_is_command_error(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        with self.assertRaises(CommandError):
            call_command(
                "add_client_note", salon_id=other.pk,
                client_id=self.client.pk, body="Hello",
                stdout=io.StringIO())
        self.assertEqual(ClientNote.objects.count(), 0)

    def test_dry_run_never_calls_writer_and_preserves_existing(self):
        # Regression (NEDB): dry-run must not enter the writer at
        # all -- a write-then-rollback preview persists on NEDB.
        call_command(
            "add_client_note", salon_id=self.salon.pk,
            client_id=self.client.pk, body="Existing",
            stdout=io.StringIO())
        self.assertEqual(ClientNote.objects.count(), 1)
        with mock.patch(
                "clients.management.commands.add_client_note."
                "add_client_note",
                side_effect=AssertionError("writer called")):
            out = io.StringIO()
            call_command(
                "add_client_note", salon_id=self.salon.pk,
                client_id=self.client.pk, body="  Preview  ",
                author=" Desk ", dry_run=True, stdout=out)
        self.assertEqual(ClientNote.objects.count(), 1)
        self.assertIn("Preview", out.getvalue())
        self.assertIn("Desk", out.getvalue())

    def test_dry_run_unknown_client_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "add_client_note", salon_id=self.salon.pk,
                client_id=999999, body="Hello", dry_run=True,
                stdout=io.StringIO())
        self.assertEqual(ClientNote.objects.count(), 0)
