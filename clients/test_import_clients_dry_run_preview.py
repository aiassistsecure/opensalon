"""Preview-twin tests for import_clients --dry-run (audit-138 rank 2).

The dry path must preview the IMPORT, not just describe the file:
would-create / would-update / would-unchanged / would-refuse counts
keyed on the importer's own identity rule, refused rows named by
index with reason, opt-in flags as they would land, notes counted --
all from reads only, with an explicit no-writes assertion.

Synthetic records only -- no real salon/client data.
"""
import io
import json

from django.core.management import call_command
from django.test import TestCase

from clients.models import Client, ClientNote
from clients.test_import_clients import FIXTURE, _write
from saloncore.models import Salon


def _run_dry(payload, **kwargs):
    out = io.StringIO()
    call_command("import_clients", _write(payload),
                 dry_run=True, stdout=out, **kwargs)
    return json.loads(out.getvalue())


def _run_real(payload, **kwargs):
    out = io.StringIO()
    call_command("import_clients", _write(payload), stdout=out, **kwargs)
    line = [ln for ln in out.getvalue().splitlines()
            if ln.startswith("IMPORT_SUMMARY ")][0]
    return json.loads(line[len("IMPORT_SUMMARY "):])


class ImportClientsPreviewCountsTests(TestCase):
    def test_counts_and_refused_rows_by_index_with_reason(self):
        preview = _run_dry(FIXTURE)["import_preview"]
        self.assertFalse(preview["salon_exists"])
        self.assertEqual(preview["records_total"], 7)
        self.assertEqual(preview["would_create"], 2)
        self.assertEqual(preview["would_update"], 0)
        self.assertEqual(preview["would_unchanged"], 0)
        self.assertEqual(preview["would_refuse"], 5)
        refused = {r["index"]: r["reason"] for r in preview["refused"]}
        self.assertEqual(sorted(refused), [2, 3, 4, 5, 6])
        self.assertIn("archived", refused[2])
        self.assertIn("deleted", refused[3])
        self.assertIn("banned", refused[4])
        self.assertIn("clientId", refused[5])
        self.assertIn("not an object", refused[6])

    def test_preview_counts_match_real_run_then_all_unchanged(self):
        preview = _run_dry(FIXTURE)["import_preview"]
        summary = _run_real(FIXTURE)
        self.assertEqual(preview["would_create"], summary["created"])
        self.assertEqual(preview["would_update"], summary["updated"])
        self.assertEqual(preview["would_unchanged"], summary["unchanged"])
        self.assertEqual(preview["would_refuse"], summary["skipped"])
        again = _run_dry(FIXTURE)["import_preview"]
        self.assertTrue(again["salon_exists"])
        self.assertEqual(again["would_create"], 0)
        self.assertEqual(again["would_update"], 0)
        self.assertEqual(again["would_unchanged"], 2)
        self.assertEqual(again["would_refuse"], 5)

    def test_existing_book_create_update_unchanged_split(self):
        _run_real(FIXTURE)
        changed = json.loads(json.dumps(FIXTURE))
        changed[1]["mobile"] = "555-9999"
        rows = [changed[0], changed[1],
                {"clientId": "cli-new", "firstName": "New",
                 "lastName": "Row", "mobile": "555-0200"}]
        preview = _run_dry(rows)["import_preview"]
        self.assertEqual(preview["would_unchanged"], 1)
        self.assertEqual(preview["would_update"], 1)
        self.assertEqual(preview["would_create"], 1)
        outcomes = {r["index"]: r["outcome"] for r in preview["records"]}
        self.assertEqual(outcomes, {0: "would_unchanged",
                                    1: "would_update",
                                    2: "would_create"})

    def test_in_file_duplicates_fold_like_the_writer(self):
        rows = [
            {"clientId": "cli-dup", "firstName": "First",
             "lastName": "Version", "mobile": "555-0200"},
            {"clientId": "cli-dup", "firstName": "Second",
             "lastName": "Version", "mobile": "555-0200"},
            {"clientId": "cli-same", "firstName": "Same",
             "lastName": "Version", "mobile": "555-0201"},
            {"clientId": "cli-same", "firstName": "Same",
             "lastName": "Version", "mobile": "555-0201"},
        ]
        preview = _run_dry(rows)["import_preview"]
        self.assertEqual(preview["would_create"], 2)
        self.assertEqual(preview["would_update"], 1)
        self.assertEqual(preview["would_unchanged"], 1)


class ImportClientsPreviewOptInTests(TestCase):
    def test_opt_ins_previewed_as_they_would_land(self):
        preview = _run_dry(FIXTURE)["import_preview"]
        records = {r["index"]: r for r in preview["records"]}
        # cli-1: both email consents true, sms reminder missing.
        self.assertTrue(records[0]["email_opt_in"])
        self.assertFalse(records[0]["sms_opt_in"])
        self.assertTrue(records[0]["active"])
        # cli-2: reminder-only email consent lands opted out (AND rule).
        self.assertFalse(records[1]["email_opt_in"])
        self.assertTrue(records[1]["sms_opt_in"])
        self.assertEqual(preview["opt_in_totals"],
                         {"email_opt_in_true": 1, "sms_opt_in_true": 1})

    def test_export_shape_opt_ins_and_active_previewed(self):
        rows = [{"external_id": "ext-1", "first_name": "Syn",
                 "last_name": "Thetic", "email_opt_in": True,
                 "sms_opt_in": "false", "active": False}]
        preview = _run_dry(rows)["import_preview"]
        self.assertEqual(preview["would_create"], 1)
        record = preview["records"][0]
        self.assertTrue(record["email_opt_in"])
        self.assertFalse(record["sms_opt_in"])
        self.assertFalse(record["active"])


class ImportClientsPreviewRefusalTests(TestCase):
    def test_invalid_rows_named_by_index_with_reason(self):
        rows = [
            {"clientId": "cli-junk", "firstName": "Junk",
             "emailMarketingConsent": "maybe"},
            {"external_id": "x" * 65, "first_name": "Too",
             "last_name": "Long"},
            {"first_name": "No", "last_name": "Identity"},
            {"external_id": "", "first_name": "Blank",
             "last_name": "Identity"},
            {"clientId": "cli-flag", "archived": "banana"},
        ]
        preview = _run_dry(rows)["import_preview"]
        self.assertEqual(preview["would_refuse"], 5)
        self.assertEqual(preview["would_create"], 0)
        refused = {r["index"]: r["reason"] for r in preview["refused"]}
        self.assertIn("emailMarketingConsent", refused[0])
        self.assertIn("exceeds", refused[1])
        self.assertIn("external_id", refused[2])
        self.assertIn("external_id", refused[3])
        self.assertIn("archived", refused[4])


class ImportClientsPreviewNotesTests(TestCase):
    PAYLOAD = [{
        "external_id": "cli-n1", "first_name": "Note",
        "last_name": "Case",
        "notes": [
            {"body": "A note", "author_name": "Desk"},
            {"body": "A note", "author_name": "Desk"},
            {"body": "", "author_name": "Desk"},
            "not-a-note",
        ],
    }]

    def test_notes_counted_and_never_written(self):
        preview = _run_dry(self.PAYLOAD)["import_preview"]
        self.assertEqual(preview["notes_would_create"], 1)
        self.assertEqual(preview["notes_would_skip"], 3)
        self.assertEqual(ClientNote.objects.count(), 0)
        _run_real(self.PAYLOAD)
        self.assertEqual(ClientNote.objects.count(), 1)
        again = _run_dry(self.PAYLOAD)["import_preview"]
        self.assertEqual(again["notes_would_create"], 0)
        self.assertEqual(again["notes_would_skip"], 4)
        self.assertEqual(ClientNote.objects.count(), 1)


class ImportClientsPreviewNoWritesTests(TestCase):
    def test_dry_run_writes_nothing_explicitly(self):
        _run_real(FIXTURE)
        before = (Salon.objects.count(), Client.objects.count(),
                  ClientNote.objects.count(),
                  Client.objects.get(external_id="cli-2").phone)
        changed = json.loads(json.dumps(FIXTURE))
        changed[1]["mobile"] = "555-9999"
        preview = _run_dry(changed)["import_preview"]
        self.assertEqual(preview["would_update"], 1)
        after = (Salon.objects.count(), Client.objects.count(),
                 ClientNote.objects.count(),
                 Client.objects.get(external_id="cli-2").phone)
        self.assertEqual(before, after)

    def test_dry_run_creates_no_salon_client_or_note(self):
        preview = _run_dry(FIXTURE, salon="Preview Only Salon")
        self.assertEqual(preview["import_preview"]["would_create"], 2)
        self.assertFalse(
            Salon.objects.filter(name="Preview Only Salon").exists())
        self.assertEqual(Client.objects.count(), 0)
        self.assertEqual(ClientNote.objects.count(), 0)


class ImportClientsPreviewShapeKeptTests(TestCase):
    def test_shape_report_verbatim_alongside_preview(self):
        report = _run_dry(FIXTURE)
        # Shape report covers the 6 object records; the non-object
        # row is named in the preview's refused list instead.
        self.assertEqual(report["record_count"], 6)
        self.assertIn("clientId", report["mapped_keys"])
        self.assertEqual(report["fields"]["firstName"]["valued"], 6)
        self.assertIn("import_preview", report)
