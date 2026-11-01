"""Tests for the import_clients management command.

The fixture below is a tiny hand-written JSON document in the shape of
a real clients export — unit logic only, no real salon data.
"""
import datetime
import io
import json
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from clients.export_all import export_all_clients
from clients.models import Client, ClientNote
from saloncore.models import Salon

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

    def test_rerun_skips_unchanged_and_updates_changed_in_place(self):
        self.run_import()
        changed = json.loads(json.dumps(FIXTURE))
        changed[0]["mobile"] = "555-9999"
        out = self.run_import(payload=changed)
        self.assertIn('"created": 0', out)
        self.assertIn('"updated": 1', out)
        self.assertIn('"unchanged": 1', out)
        self.assertEqual(Client.objects.count(), 2)
        self.assertEqual(
            Client.objects.get(external_id="cli-1").phone, "555-9999")

    def test_rerun_without_changes_is_all_unchanged(self):
        self.run_import()
        out = self.run_import()
        self.assertIn('"created": 0', out)
        self.assertIn('"updated": 0', out)
        self.assertIn('"unchanged": 2', out)
        self.assertEqual(Client.objects.count(), 2)

    def test_duplicate_id_in_one_file_folds_into_one_row(self):
        payload = [
            {"clientId": "cli-dup", "firstName": "First",
             "lastName": "Version", "mobile": "555-0200"},
            {"clientId": "cli-dup", "firstName": "Second",
             "lastName": "Version", "mobile": "555-0200"},
        ]
        out = self.run_import(payload=payload)
        self.assertIn('"created": 1', out)
        self.assertIn('"updated": 1', out)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(
            Client.objects.get(external_id="cli-dup").first_name, "Second")

    def test_identical_duplicate_in_one_file_is_unchanged(self):
        row = {"clientId": "cli-dup", "firstName": "Same",
               "lastName": "Version", "mobile": "555-0200"}
        out = self.run_import(payload=[row, dict(row)])
        self.assertIn('"created": 1', out)
        self.assertIn('"unchanged": 1', out)
        self.assertEqual(Client.objects.count(), 1)

    def test_same_external_id_in_another_salon_is_separate(self):
        self.run_import()
        self.run_import(salon="Other Salon")
        self.assertEqual(Client.objects.count(), 4)
        self.assertEqual(
            Client.objects.filter(salon__name="Other Salon").count(), 2)

class ImportClientsNaiveDatetimeTests(TestCase):
    """TF-7a: naive note datetimes are made aware in the salon zone
    and counted; unparseable ones are counted as dropped."""

    def setUp(self):
        self.salon = Salon.objects.create(
            name="TZ Salon", timezone="America/New_York")

    def run_import(self, payload):
        out = io.StringIO()
        call_command("import_clients", _write(payload),
                     salon="TZ Salon", stdout=out)
        return out.getvalue()

    @staticmethod
    def _summary(out):
        line = [ln for ln in out.splitlines()
                if ln.startswith("IMPORT_SUMMARY ")][0]
        return json.loads(line[len("IMPORT_SUMMARY "):])

    @staticmethod
    def _payload(created_at):
        return [{
            "external_id": "cli-tz-1", "first_name": "Tz",
            "last_name": "Case",
            "notes": [{"body": "A note", "author_name": "Desk",
                       "created_at": created_at}],
        }]

    def test_naive_datetime_made_aware_in_salon_zone_and_counted(self):
        out = self.run_import(self._payload("2026-01-15T10:00:00"))
        summary = self._summary(out)
        self.assertEqual(summary["naive_datetimes_made_aware"], 1)
        self.assertEqual(summary["datetimes_dropped"], 0)
        note = ClientNote.objects.get()
        self.assertTrue(timezone.is_aware(note.created_at))
        # 10:00 in America/New_York in January is EST (UTC-5).
        self.assertEqual(
            note.created_at,
            datetime.datetime(2026, 1, 15, 15, 0,
                              tzinfo=datetime.timezone.utc))

    def test_garbage_datetime_counted_dropped_note_still_imports(self):
        out = self.run_import(self._payload("not-a-date"))
        summary = self._summary(out)
        self.assertEqual(summary["datetimes_dropped"], 1)
        self.assertEqual(summary["naive_datetimes_made_aware"], 0)
        self.assertEqual(summary["notes_created"], 1)
        note = ClientNote.objects.get()
        self.assertEqual(note.body, "A note")
        # No fabricated timestamp: the automatic aware timestamp stands.
        self.assertTrue(timezone.is_aware(note.created_at))

    def test_already_aware_datetime_unchanged_no_counts(self):
        out = self.run_import(
            self._payload("2026-01-15T10:00:00+00:00"))
        summary = self._summary(out)
        self.assertEqual(summary["naive_datetimes_made_aware"], 0)
        self.assertEqual(summary["datetimes_dropped"], 0)
        note = ClientNote.objects.get()
        self.assertEqual(
            note.created_at,
            datetime.datetime(2026, 1, 15, 10, 0,
                              tzinfo=datetime.timezone.utc))


class ImportClientsPayloadTests(TestCase):
    """TF-10: the verbatim source record is retained in payload."""

    def run_import(self, payload, **kwargs):
        out = io.StringIO()
        call_command("import_clients", _write(payload), stdout=out, **kwargs)
        return out.getvalue()

    def test_phorest_payload_stored_verbatim(self):
        row = {
            "clientId": "cli-p1", "firstName": "Pay", "lastName": "Load",
            "email": "pay.load@example.com", "mobile": "555-0300",
            "emailMarketingConsent": True, "emailReminderConsent": True,
            "extraUnmappedField": "kept-me",
            "nestedExtra": {"channel": "phone", "flags": ["a", "b"]},
        }
        self.run_import([row])
        client = Client.objects.get(external_id="cli-p1")
        self.assertEqual(client.payload, row)
        self.assertEqual(client.payload["extraUnmappedField"], "kept-me")

    def test_phorest_payload_set_without_extras(self):
        row = {"clientId": "cli-p2", "firstName": "Plain",
               "lastName": "Row", "mobile": "555-0301"}
        self.run_import([row])
        self.assertEqual(
            Client.objects.get(external_id="cli-p2").payload, row)

    def test_export_shape_payload_restored_verbatim(self):
        original = {"clientId": "cli-orig", "firstName": "Orig",
                    "customSourceField": {"deep": [1, 2, 3]}}
        row = {
            "external_id": "cli-p3", "first_name": "Export",
            "last_name": "Shape", "email": "export.shape@example.com",
            "phone": "555-0302", "email_opt_in": True,
            "sms_opt_in": False, "active": True, "payload": original,
        }
        self.run_import([row])
        client = Client.objects.get(external_id="cli-p3")
        # Restored as-is, never re-wrapped in the export row.
        self.assertEqual(client.payload, original)

    def test_export_shape_without_payload_imports_with_empty_payload(self):
        row = {
            "external_id": "cli-p4", "first_name": "No",
            "last_name": "Payload", "email": "", "phone": "555-0303",
            "email_opt_in": False, "sms_opt_in": False, "active": True,
        }
        out = self.run_import([row])
        self.assertIn('"created": 1', out)
        client = Client.objects.get(external_id="cli-p4")
        self.assertFalse(client.payload)

    def test_payload_change_on_rerun_counts_as_update(self):
        row = {"clientId": "cli-p5", "firstName": "Before",
               "lastName": "Change", "mobile": "555-0304",
               "extraUnmappedField": "before"}
        self.run_import([row])
        out = self.run_import([row])
        self.assertIn('"unchanged": 1', out)
        changed = dict(row, extraUnmappedField="after")
        out = self.run_import([changed])
        self.assertIn('"updated": 1', out)
        self.assertEqual(
            Client.objects.get(external_id="cli-p5").payload, changed)

    def test_payload_survives_export_and_reimport_round_trip(self):
        row = {
            "clientId": "cli-p6", "firstName": "Round", "lastName": "Trip",
            "email": "round.trip@example.com", "mobile": "555-0305",
            "emailMarketingConsent": True, "emailReminderConsent": True,
            "smsMarketingConsent": True, "smsReminderConsent": True,
            "extraUnmappedField": "kept-me",
        }
        self.run_import([row], salon="Source Salon")
        source = Salon.objects.get(name="Source Salon")
        records = export_all_clients(salon=source)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["payload"], row)
        out = self.run_import(records, salon="Target Salon")
        self.assertIn('"created": 1', out)
        imported = Client.objects.get(
            salon__name="Target Salon", external_id="cli-p6")
        self.assertEqual(imported.payload, row)


class ImportClientsExternalIdLengthTests(TestCase):
    """TF-6: over-long ids are skipped+counted, never truncated."""

    AT_LIMIT = "x" * 64
    OVER_LIMIT = "x" * 65

    def run_import(self, payload, **kwargs):
        out = io.StringIO()
        call_command("import_clients", _write(payload), stdout=out, **kwargs)
        return out.getvalue()

    @staticmethod
    def _summary(out):
        line = [ln for ln in out.splitlines()
                if ln.startswith("IMPORT_SUMMARY ")][0]
        return json.loads(line[len("IMPORT_SUMMARY "):])

    def test_overlong_phorest_client_id_skipped_and_counted(self):
        row = {"clientId": self.OVER_LIMIT, "firstName": "Too",
               "lastName": "Long", "mobile": "555-0400"}
        out = self.run_import([row])
        summary = self._summary(out)
        self.assertEqual(summary["skipped_external_id_too_long"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["created"], 0)
        self.assertEqual(Client.objects.count(), 0)
        # No silently truncated identity was stored.
        self.assertFalse(
            Client.objects.filter(external_id=self.AT_LIMIT).exists())

    def test_overlong_export_external_id_skipped_and_counted(self):
        row = {"external_id": self.OVER_LIMIT, "first_name": "Too",
               "last_name": "Long", "phone": "555-0401"}
        out = self.run_import([row])
        summary = self._summary(out)
        self.assertEqual(summary["skipped_external_id_too_long"], 1)
        self.assertEqual(Client.objects.count(), 0)

    def test_overlong_fallback_id_skipped_and_counted(self):
        row = {"id": self.OVER_LIMIT, "firstName": "Fallback",
               "lastName": "Long", "mobile": "555-0402"}
        out = self.run_import([row])
        summary = self._summary(out)
        self.assertEqual(summary["skipped_external_id_too_long"], 1)
        self.assertEqual(Client.objects.count(), 0)

    def test_at_limit_ids_import_exactly(self):
        rows = [
            {"clientId": self.AT_LIMIT, "firstName": "At",
             "lastName": "Limit", "mobile": "555-0403"},
            {"external_id": "y" * 64, "first_name": "At",
             "last_name": "Limit", "phone": "555-0404"},
        ]
        out = self.run_import(rows)
        summary = self._summary(out)
        self.assertEqual(summary["created"], 2)
        self.assertEqual(summary["skipped_external_id_too_long"], 0)
        self.assertTrue(
            Client.objects.filter(external_id=self.AT_LIMIT).exists())
        self.assertTrue(
            Client.objects.filter(external_id="y" * 64).exists())

    def test_normal_ids_unaffected(self):
        row = {"clientId": "cli-short", "firstName": "Normal",
               "lastName": "Row", "mobile": "555-0405"}
        out = self.run_import([row])
        summary = self._summary(out)
        self.assertEqual(summary["created"], 1)
        self.assertEqual(summary["skipped_external_id_too_long"], 0)
        self.assertTrue(
            Client.objects.filter(external_id="cli-short").exists())

    def test_reimport_is_idempotent_for_at_limit_and_overlong(self):
        at_limit = {"clientId": self.AT_LIMIT, "firstName": "At",
                    "lastName": "Limit", "mobile": "555-0406"}
        overlong = {"clientId": self.OVER_LIMIT, "firstName": "Too",
                    "lastName": "Long", "mobile": "555-0407"}
        self.run_import([at_limit, overlong])
        out = self.run_import([at_limit, overlong])
        summary = self._summary(out)
        self.assertEqual(summary["created"], 0)
        self.assertEqual(summary["unchanged"], 1)
        self.assertEqual(summary["skipped_external_id_too_long"], 1)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(
            Client.objects.get().external_id, self.AT_LIMIT)


class ImportClientsDryRunTests(TestCase):
    """TF-12 wiring: --dry-run reports via saloncore.dry_run and
    writes nothing; a normal import of the same fixture still works."""

    # Record 1 carries a null email, an empty-string mobile and an
    # unmapped key; record 2 omits email and mobile entirely, so the
    # report's null / missing / empty_string counts are distinct.
    FIXTURE = [
        {
            "clientId": "dry-1", "firstName": "Dry", "lastName": "Run",
            "email": None, "mobile": "",
            "legacySourceField": "not-mapped",
            "notes": [{"body": "must not import", "author_name": "Desk"}],
        },
        {"clientId": "dry-2", "firstName": "Second", "lastName": "Row"},
    ]

    def run_dry(self, payload=None):
        path = _write(self.FIXTURE if payload is None else payload)
        out = io.StringIO()
        call_command("import_clients", path, dry_run=True, stdout=out)
        return path, json.loads(out.getvalue())

    def test_dry_run_writes_nothing(self):
        self.run_dry()
        self.assertEqual(Client.objects.count(), 0)
        self.assertEqual(ClientNote.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 0)

    def test_dry_run_report_names_unmapped_key(self):
        path, report = self.run_dry()
        self.assertEqual(report["source"], path)
        self.assertEqual(report["record_count"], 2)
        self.assertIn("legacySourceField", report["unmapped_keys"])
        self.assertNotIn("legacySourceField", report["mapped_keys"])
        for mapped in ("clientId", "firstName", "mobile",
                       "emailMarketingConsent", "external_id",
                       "first_name", "phone", "email_opt_in",
                       "active", "payload", "notes"):
            self.assertIn(mapped, report["mapped_keys"])
        self.assertNotIn("IMPORT_SUMMARY", json.dumps(report))

    def test_dry_run_distinguishes_null_missing_and_empty_string(self):
        _, report = self.run_dry()
        email = report["fields"]["email"]
        self.assertEqual(email["null"], 1)        # record 1: None
        self.assertEqual(email["missing"], 1)     # record 2: absent
        self.assertEqual(email["empty_string"], 0)
        mobile = report["fields"]["mobile"]
        self.assertEqual(mobile["empty_string"], 1)  # record 1: ""
        self.assertEqual(mobile["missing"], 1)       # record 2: absent
        self.assertEqual(mobile["null"], 0)
        first = report["fields"]["firstName"]
        self.assertEqual(first["valued"], 2)
        self.assertEqual(first["inferred_type"], "string")

    def test_normal_import_of_same_fixture_still_works(self):
        out = io.StringIO()
        call_command(
            "import_clients", _write(self.FIXTURE), stdout=out)
        self.assertIn('"created": 2', out.getvalue())
        self.assertEqual(Client.objects.count(), 2)
        self.assertEqual(ClientNote.objects.count(), 1)
        self.assertEqual(
            Client.objects.get(external_id="dry-1").first_name, "Dry")


class ImportClientsFileErrorTests(TestCase):
    def test_missing_file_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("import_clients", "/nonexistent/clients.json")

    def test_invalid_json_raises_command_error(self):
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        fh.write("{not json")
        fh.close()
        with self.assertRaises(CommandError):
            call_command("import_clients", fh.name)
