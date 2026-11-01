"""Regression tests: import_clients parses booleans strictly (TF-1).

Probe 1 of the cycle-59 importer type audit: all four Phorest
consents as the string ``"false"`` imported as
``email_opt_in=True, sms_opt_in=True`` because ``bool("false")``
is ``True``. A non-consenting client must never become opted in.

Synthetic records only — no real salon/client data.
"""
import io
import json
import tempfile

from django.core.management import call_command
from django.test import TestCase

from clients.models import Client


def _write(payload):
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fh)
    fh.close()
    return fh.name


def _import(payload):
    out = io.StringIO()
    call_command("import_clients", _write(payload), stdout=out)
    return out.getvalue()


def _phorest(client_id, **overrides):
    row = {
        "clientId": client_id, "firstName": "Syn", "lastName": "Thetic",
        "email": "", "mobile": "555-0199",
        "emailMarketingConsent": True, "emailReminderConsent": True,
        "smsMarketingConsent": True, "smsReminderConsent": True,
        "archived": False, "deleted": False, "banned": False,
    }
    row.update(overrides)
    return row


class PhorestStringBoolTests(TestCase):
    def test_string_false_consents_import_as_opted_out(self):
        out = _import([_phorest(
            "cli-sf",
            emailMarketingConsent="false", emailReminderConsent="false",
            smsMarketingConsent="false", smsReminderConsent="false")])
        self.assertIn('"created": 1', out)
        client = Client.objects.get(external_id="cli-sf")
        self.assertFalse(client.email_opt_in)
        self.assertFalse(client.sms_opt_in)

    def test_string_false_is_case_insensitive_and_mixed(self):
        _import([_phorest(
            "cli-mixed",
            emailMarketingConsent="TRUE", emailReminderConsent="True",
            smsMarketingConsent="true", smsReminderConsent="FALSE")])
        client = Client.objects.get(external_id="cli-mixed")
        self.assertTrue(client.email_opt_in)
        self.assertFalse(client.sms_opt_in)

    def test_string_yes_no_and_numeric_strings_parse(self):
        _import([
            _phorest("cli-yes",
                     emailMarketingConsent="yes",
                     emailReminderConsent="1",
                     smsMarketingConsent="no", smsReminderConsent="1"),
            _phorest("cli-zero",
                     emailMarketingConsent="0", emailReminderConsent="1",
                     smsMarketingConsent="0", smsReminderConsent="0"),
        ])
        yes = Client.objects.get(external_id="cli-yes")
        self.assertTrue(yes.email_opt_in)
        self.assertFalse(yes.sms_opt_in)
        zero = Client.objects.get(external_id="cli-zero")
        self.assertFalse(zero.email_opt_in)
        self.assertFalse(zero.sms_opt_in)

    def test_int_one_and_zero_consents_parse(self):
        _import([_phorest(
            "cli-int", emailMarketingConsent=1, emailReminderConsent=1,
            smsMarketingConsent=0, smsReminderConsent=1)])
        client = Client.objects.get(external_id="cli-int")
        self.assertTrue(client.email_opt_in)
        self.assertFalse(client.sms_opt_in)

    def test_string_false_flags_do_not_skip_client(self):
        out = _import([_phorest(
            "cli-flags", archived="false", deleted="False",
            banned="no")])
        self.assertIn('"created": 1', out)
        self.assertTrue(Client.objects.filter(
            external_id="cli-flags").exists())

    def test_string_true_flags_skip_client(self):
        out = _import([
            _phorest("cli-arch", archived="true"),
            _phorest("cli-del", deleted="yes"),
            _phorest("cli-ban", banned="1"),
        ])
        self.assertIn('"skipped": 3', out)
        self.assertEqual(Client.objects.count(), 0)


class ExportStringBoolTests(TestCase):
    def test_string_false_opt_ins_and_active_import_as_false(self):
        out = _import([{
            "external_id": "ext-sf", "first_name": "Syn",
            "last_name": "Thetic", "email": "", "phone": "555-0198",
            "email_opt_in": "false", "sms_opt_in": "false",
            "active": "false",
        }])
        self.assertIn('"created": 1', out)
        client = Client.objects.get(external_id="ext-sf")
        self.assertFalse(client.email_opt_in)
        self.assertFalse(client.sms_opt_in)
        self.assertFalse(client.active)

    def test_string_true_opt_ins_and_active_import_as_true(self):
        _import([{
            "external_id": "ext-st", "first_name": "Syn",
            "last_name": "Thetic", "email": "", "phone": "555-0197",
            "email_opt_in": "yes", "sms_opt_in": "1", "active": "TRUE",
        }])
        client = Client.objects.get(external_id="ext-st")
        self.assertTrue(client.email_opt_in)
        self.assertTrue(client.sms_opt_in)
        self.assertTrue(client.active)


class JunkBoolTests(TestCase):
    def test_junk_consent_skips_row_and_never_opts_in(self):
        out = _import([
            _phorest("cli-junk", emailMarketingConsent="maybe"),
            _phorest("cli-good"),
        ])
        self.assertIn('"created": 1', out)
        self.assertIn('"skipped": 1', out)
        self.assertFalse(Client.objects.filter(
            external_id="cli-junk").exists())
        self.assertTrue(Client.objects.get(
            external_id="cli-good").email_opt_in)

    def test_junk_flag_and_export_values_skip_rows(self):
        out = _import([
            _phorest("cli-junk-flag", archived="banana"),
            {"external_id": "ext-junk", "first_name": "Syn",
             "last_name": "Thetic", "email_opt_in": "sometimes",
             "sms_opt_in": False, "active": True},
            {"external_id": "ext-junk-active", "first_name": "Syn",
             "last_name": "Thetic", "email_opt_in": False,
             "sms_opt_in": False, "active": 2},
        ])
        self.assertIn('"skipped": 3', out)
        self.assertEqual(Client.objects.count(), 0)

    def test_junk_types_skip_rows(self):
        out = _import([
            _phorest("cli-junk-list", smsMarketingConsent=["true"]),
            _phorest("cli-junk-num", emailReminderConsent=7),
        ])
        self.assertIn('"skipped": 2', out)
        self.assertEqual(Client.objects.count(), 0)
