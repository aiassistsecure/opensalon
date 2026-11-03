"""Tests for the set_client_opt_ins management command.

Synthetic fixtures only -- no real salon/client data. The command
is a thin wrapper around ``clients.optins.update_client_opt_ins``;
these tests verify the real run delegates verbatim, --dry-run
previews without writing, and salon scoping / invalid input
handling apply. Output is checked for ids and flag values only.
"""
import io

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client
from saloncore.models import Salon


class SetClientOptInsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Amy", last_name="Smith",
            email="amy@example.com",
        )

    def fresh(self):
        return Client.objects.get(pk=self.client.pk)

    def _run(self, **kwargs):
        out = io.StringIO()
        call_command("set_client_opt_ins", stdout=out, **kwargs)
        return out.getvalue()

    def test_real_run_sets_both_flags(self):
        text = self._run(
            salon_id=self.salon.id, client_id=self.client.id,
            sms_opt_in="true", email_opt_in="true",
        )
        fresh = self.fresh()
        self.assertTrue(fresh.sms_opt_in)
        self.assertTrue(fresh.email_opt_in)
        self.assertIn("sms_opt_in: False -> True", text)
        self.assertIn("email_opt_in: False -> True", text)
        self.assertNotIn("amy@example.com", text)

    def test_real_run_partial_leaves_other_flag(self):
        self.client.email_opt_in = True
        self.client.save()
        self._run(
            salon_id=self.salon.id, client_id=self.client.id,
            sms_opt_in="true",
        )
        fresh = self.fresh()
        self.assertTrue(fresh.sms_opt_in)
        self.assertTrue(fresh.email_opt_in)

    def test_real_run_opt_out(self):
        self.client.sms_opt_in = True
        self.client.save()
        text = self._run(
            salon_id=self.salon.id, client_id=self.client.id,
            sms_opt_in="false",
        )
        self.assertFalse(self.fresh().sms_opt_in)
        self.assertIn("sms_opt_in: True -> False", text)

    def test_real_run_no_change_reports_no_changes(self):
        text = self._run(
            salon_id=self.salon.id, client_id=self.client.id,
            sms_opt_in="false",
        )
        self.assertIn("no changes", text)
        self.assertFalse(self.fresh().sms_opt_in)

    def test_dry_run_previews_and_writes_nothing(self):
        text = self._run(
            salon_id=self.salon.id, client_id=self.client.id,
            sms_opt_in="true", email_opt_in="true", dry_run=True,
        )
        self.assertIn("dry-run", text)
        self.assertIn("would set sms_opt_in: False -> True", text)
        self.assertIn("would set email_opt_in: False -> True", text)
        fresh = self.fresh()
        self.assertFalse(fresh.sms_opt_in)
        self.assertFalse(fresh.email_opt_in)

    def test_dry_run_no_change(self):
        text = self._run(
            salon_id=self.salon.id, client_id=self.client.id,
            sms_opt_in="false", dry_run=True,
        )
        self.assertIn("no changes", text)
        self.assertFalse(self.fresh().sms_opt_in)

    def test_dry_run_only_differing_flag_listed(self):
        self.client.email_opt_in = True
        self.client.save()
        text = self._run(
            salon_id=self.salon.id, client_id=self.client.id,
            sms_opt_in="true", email_opt_in="true", dry_run=True,
        )
        self.assertIn("would set sms_opt_in", text)
        self.assertNotIn("would set email_opt_in", text)
        self.assertFalse(self.fresh().sms_opt_in)

    def test_neither_flag_raises(self):
        with self.assertRaises(CommandError):
            self._run(salon_id=self.salon.id, client_id=self.client.id)

    def test_neither_flag_dry_run_also_raises(self):
        with self.assertRaises(CommandError):
            self._run(
                salon_id=self.salon.id, client_id=self.client.id,
                dry_run=True,
            )

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            self._run(
                salon_id=999999, client_id=self.client.id,
                sms_opt_in="true",
            )

    def test_unknown_client_raises(self):
        with self.assertRaises(CommandError):
            self._run(
                salon_id=self.salon.id, client_id=999999,
                sms_opt_in="true",
            )

    def test_cross_salon_client_raises_and_unchanged(self):
        other_client = Client.objects.create(
            salon=self.other_salon, first_name="Bob", last_name="Adams",
        )
        with self.assertRaises(CommandError):
            self._run(
                salon_id=self.salon.id, client_id=other_client.id,
                sms_opt_in="true",
            )
        other_client.refresh_from_db()
        self.assertFalse(other_client.sms_opt_in)
