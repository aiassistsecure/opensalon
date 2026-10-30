"""Tests for the import_clients management command.

The fixture below is a tiny hand-written JSON document in the shape of
a real clients export — unit logic only, no real salon data.
"""
import io
import json
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client

FIXTURE = [
    {
        "clientId": "cli-1", "firstName": "Test", "lastName": "Example",
        "email": "test.example@example.com", "mobile": "555-0100",
        "emailMarketingConsent": True, "emailReminderConsent": True,
        "smsMarketingConsent": True, "smsReminderConsent": False,
        "archived": False, "deleted": False, "banned": False,
    },
    {
        # Reminder-only email consent: the model's single email_opt_in
        # gates marketing too, so this imports as opted out (AND rule).
        "clientId": "cli-2", "firstName": "Reminder", "lastName": "Only",
        "email": "", "mobile": "555-0101",
        "emailMarketingConsent": False, "emailReminderConsent": True,
        "smsMarketingConsent": True, "smsReminderConsent": True,
    },
    {"clientId": "cli-3", "firstName": "Gone", "lastName": "Archived",
     "archived": True},
    {"clientId": "cli-4", "firstName": "Gone", "lastName": "Deleted",
     "deleted": True},
    {"clientId": "cli-5", "firstName": "Gone", "lastName": "Banned",
     "banned": True},
    {"firstName": "No", "lastName": "StableId"},  # no clientId: skipped
    "not-a-dict",
]


def _write(payload):
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fh)
    fh.close()
    return fh.name


class ImportClientsTests(TestCase):
    def run_import(self, payload=FIXTURE, **kwargs):
        out = io.StringIO()
        call_command("import_clients", _write(payload), stdout=out, **kwargs)
        return out.getvalue()

    def test_imports_fields_and_stores_client_id(self):
        out = self.run_import()
        self.assertIn("IMPORT_SUMMARY", out)
        self.assertIn('"created": 2', out)
        self.assertIn('"skipped": 5', out)
        client = Client.objects.get(external_id="cli-1")
        self.assertEqual(client.first_name, "Test")
        self.assertEqual(client.last_name, "Example")
        self.assertEqual(client.email, "test.example@example.com")
        self.assertEqual(client.phone, "555-0100")
        self.assertTrue(client.active)

    def test_consent_mapping_requires_both_consents(self):
        self.run_import()
        both = Client.objects.get(external_id="cli-1")
        self.assertTrue(both.email_opt_in)   # marketing AND reminder
        self.assertFalse(both.sms_opt_in)    # reminder consent missing
        reminder_only = Client.objects.get(external_id="cli-2")
        self.assertFalse(reminder_only.email_opt_in)
        self.assertTrue(reminder_only.sms_opt_in)

    def test_archived_deleted_banned_are_skipped(self):
        self.run_import()
        self.assertEqual(Client.objects.count(), 2)
        for gone in ("cli-3", "cli-4", "cli-5"):
            self.assertFalse(Client.objects.filter(external_id=gone).exists())

    def test_rerun_is_idempotent_and_updates_in_place(self):
        self.run_import()
        changed = json.loads(json.dumps(FIXTURE))
        changed[0]["mobile"] = "555-9999"
        out = self.run_import(payload=changed)
        self.assertIn('"created": 0', out)
        self.assertIn('"updated": 2', out)
        self.assertEqual(Client.objects.count(), 2)
        self.assertEqual(
            Client.objects.get(external_id="cli-1").phone, "555-9999")

    def test_same_external_id_in_another_salon_is_separate(self):
        self.run_import()
        self.run_import(salon="Other Salon")
        self.assertEqual(Client.objects.count(), 4)
        self.assertEqual(
            Client.objects.filter(salon__name="Other Salon").count(), 2)

    def test_missing_file_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("import_clients", "/nonexistent/clients.json")

    def test_invalid_json_raises_command_error(self):
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        fh.write("{not json")
        fh.close()
        with self.assertRaises(CommandError):
            call_command("import_clients", fh.name)
