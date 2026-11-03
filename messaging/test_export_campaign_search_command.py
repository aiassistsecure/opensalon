import io
import os
import tempfile
from datetime import date

from django.core.management import CommandError, call_command
from django.test import TestCase

from messaging.campaign_search_export import export_campaign_search_csv
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
