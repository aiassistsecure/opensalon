import io
import json
import os
import tempfile
from datetime import date
from unittest import mock

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from messaging.campaign_search_export import (
    export_campaign_search,
    export_campaign_search_csv,
)
from messaging.models import Campaign
from saloncore.models import Salon

DAY1 = date(2026, 3, 2)


class ExportCampaignSearchCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        Campaign.objects.create(
            salon=self.salon, name="Spring Offer",
            channel="sms", body="Hello")
        Campaign.objects.create(
            salon=self.salon, name="Spring Email",
            channel="email", subject="Hi", body="Body")
        Campaign.objects.create(
            salon=self.other, name="Spring Other",
            channel="sms", body="Hello")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_campaign_search", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(
            out.getvalue(), export_campaign_search_csv(self.salon))

    def test_stdout_matches_service_with_filters(self):
        out = io.StringIO()
        call_command(
            "export_campaign_search", "--salon-id", str(self.salon.pk),
            "--term", "spring", "--channel", "sms",
            "--status", "draft", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_campaign_search_csv(
                self.salon, "spring", channel="sms", status="draft"))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_kwargs_filters_and_salon_scoping(self):
        out = io.StringIO()
        call_command(
            "export_campaign_search", salon_id=self.other.pk,
            term="spring", stdout=out)
        self.assertEqual(
            out.getvalue(), export_campaign_search_csv(self.other, "spring"))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "campaign_search.csv")
            call_command(
                "export_campaign_search", salon_id=self.salon.pk,
                term="spring", output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_campaign_search_csv(self.salon, "spring"))
        self.assertEqual(out.getvalue(), "")

    def test_default_is_csv_byte_identical(self):
        default_out = io.StringIO()
        call_command(
            "export_campaign_search", salon_id=self.salon.pk,
            stdout=default_out)
        csv_out = io.StringIO()
        call_command(
            "export_campaign_search", salon_id=self.salon.pk,
            format="csv", stdout=csv_out)
        self.assertEqual(default_out.getvalue(), csv_out.getvalue())
        self.assertEqual(
            default_out.getvalue(),
            export_campaign_search_csv(self.salon))

    def test_explicit_csv_via_cli_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_campaign_search", "--salon-id", str(self.salon.pk),
            "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(), export_campaign_search_csv(self.salon))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command(
            "export_campaign_search", salon_id=self.salon.pk,
            format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_campaign_search(self.salon))
        self.assertEqual(
            out.getvalue(),
            json.dumps(
                export_campaign_search(self.salon),
                indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_via_cli_with_filters_matches_dict_service(self):
        out = io.StringIO()
        call_command(
            "export_campaign_search", "--salon-id", str(self.salon.pk),
            "--term", "spring", "--channel", "sms",
            "--status", "draft", "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_campaign_search(
                self.salon, "spring", channel="sms", status="draft"))
        self.assertEqual(len(json.loads(out.getvalue())), 1)

    def test_json_delegates_to_dict_service_verbatim(self):
        with mock.patch(
            "messaging.management.commands.export_campaign_search"
            ".export_campaign_search",
            wraps=export_campaign_search,
        ) as spy:
            call_command(
                "export_campaign_search", salon_id=self.salon.pk,
                format="json", stdout=io.StringIO())
        spy.assert_called_once_with(
            self.salon, None, status=None, channel=None,
            start=None, end=None)

    def test_json_output_file_parses_and_equals_dict_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "campaign_search.json")
            call_command(
                "export_campaign_search", salon_id=self.salon.pk,
                term="spring", format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written),
            export_campaign_search(self.salon, "spring"))
        self.assertEqual(out.getvalue(), "")

    def test_json_service_error_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_campaign_search", salon_id=self.salon.pk,
                start=date(2026, 3, 3), end=DAY1, format="json",
                stdout=io.StringIO())

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_campaign_search", salon_id=self.salon.pk,
                format="xml", stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_campaign_search", "--salon-id", str(self.salon.pk),
                "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_campaign_search", salon_id=self.salon.pk + 1000,
                stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_campaign_search", salon_id=self.salon.pk,
                    output=path, stdout=io.StringIO())

    def test_reversed_range_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_campaign_search", salon_id=self.salon.pk,
                start=date(2026, 3, 3), end=DAY1, stdout=io.StringIO())
