"""Tests for the update_client management command.

Synthetic fixtures only -- no real salon/client data. The command
is a thin wrapper around ``clients.update_client.update_client``;
these tests verify the real run delegates verbatim, --dry-run
uses only the read-only validate twin and writes nothing, and
salon scoping / invalid input handling apply. Output is checked
for ids and field names only -- never names or contact details.
"""
import io

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client
from saloncore.models import Salon


class UpdateClientCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Amy", last_name="Smith",
            email="amy@example.com", phone="555-0101")

    def fresh(self):
        return Client.objects.get(pk=self.client.pk)

    def _run(self, **kwargs):
        out = io.StringIO()
        call_command("update_client", stdout=out, **kwargs)
        return out.getvalue()

    def test_real_run_updates_fields_without_leaking_details(self):
        text = self._run(
            salon_id=self.salon.id, client_id=self.client.id,
            first_name="Bea", email="bea@example.com", active=False)
        fresh = self.fresh()
        self.assertEqual(
            (fresh.first_name, fresh.email, fresh.active),
            ("Bea", "bea@example.com", False))
        self.assertIn("set first_name", text)
        self.assertIn("set email", text)
        self.assertIn("set active: True -> False", text)
        self.assertNotIn("bea@example.com", text)
        self.assertNotIn("Bea", text)

    def test_real_run_partial_leaves_omitted_fields(self):
        self._run(
            salon_id=self.salon.id, client_id=self.client.id,
            phone="555-0202")
        fresh = self.fresh()
        self.assertEqual(
            (fresh.first_name, fresh.email, fresh.phone),
            ("Amy", "amy@example.com", "555-0202"))

    def test_real_run_no_change_reports_no_changes(self):
        text = self._run(
            salon_id=self.salon.id, client_id=self.client.id,
            first_name="Amy")
        self.assertIn("no changes", text)

    def test_active_and_inactive_flags_via_argv(self):
        out = io.StringIO()
        call_command(
            "update_client", "--salon-id", str(self.salon.id),
            "--client-id", str(self.client.id), "--inactive",
            stdout=out)
        self.assertFalse(self.fresh().active)
        call_command(
            "update_client", "--salon-id", str(self.salon.id),
            "--client-id", str(self.client.id), "--active",
            stdout=io.StringIO())
        self.assertTrue(self.fresh().active)

    def test_dry_run_previews_and_writes_nothing(self):
        text = self._run(
            salon_id=self.salon.id, client_id=self.client.id,
            first_name="Bea", active=False, dry_run=True)
        self.assertIn("dry-run", text)
        self.assertIn("would set first_name", text)
        self.assertIn("would set active: -> False", text)
        self.assertNotIn("Bea", text)
        fresh = self.fresh()
        self.assertEqual((fresh.first_name, fresh.active), ("Amy", True))

    def test_dry_run_no_change(self):
        text = self._run(
            salon_id=self.salon.id, client_id=self.client.id,
            first_name="Amy", dry_run=True)
        self.assertIn("no changes", text)

    def test_dry_run_invalid_value_raises_and_writes_nothing(self):
        with self.assertRaises(CommandError):
            self._run(
                salon_id=self.salon.id, client_id=self.client.id,
                email="not-an-email", dry_run=True)
        self.assertEqual(self.fresh().email, "amy@example.com")

    def test_real_run_invalid_value_raises_and_writes_nothing(self):
        with self.assertRaises(CommandError):
            self._run(
                salon_id=self.salon.id, client_id=self.client.id,
                first_name="x" * 81)
        self.assertEqual(self.fresh().first_name, "Amy")

    def test_no_field_raises_in_both_modes(self):
        with self.assertRaises(CommandError):
            self._run(salon_id=self.salon.id, client_id=self.client.id)
        with self.assertRaises(CommandError):
            self._run(
                salon_id=self.salon.id, client_id=self.client.id,
                dry_run=True)

    def test_unknown_salon_and_client_raise(self):
        with self.assertRaises(CommandError):
            self._run(
                salon_id=999999, client_id=self.client.id,
                first_name="Bea")
        with self.assertRaises(CommandError):
            self._run(
                salon_id=self.salon.id, client_id=999999,
                first_name="Bea")

    def test_cross_salon_client_raises_and_unchanged(self):
        other_client = Client.objects.create(
            salon=self.other_salon, first_name="Bob", last_name="Adams")
        with self.assertRaises(CommandError):
            self._run(
                salon_id=self.salon.id, client_id=other_client.id,
                first_name="Bea")
        other_client.refresh_from_db()
        self.assertEqual(other_client.first_name, "Bob")
