"""export_campaign_audience command: wrapper over the export twin."""
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client
from messaging.campaign_audience_export import (
    export_campaign_audience_csv,
)
from messaging.models import Campaign
from saloncore.models import Salon


class ExportCampaignAudienceCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon",
                                          timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon",
                                          timezone="UTC")
        self.campaign = Campaign.objects.create(
            salon=self.salon, name="Spring Offer",
            channel="sms", body="Hello body")
        Client.objects.create(
            salon=self.salon, first_name="In", last_name="Audience",
            email="in@example.com", phone="555-0100", sms_opt_in=True)
        Client.objects.create(
            salon=self.salon, first_name="Out", last_name="Audience",
            email="out@example.com", phone="555-0101")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_campaign_audience",
                     campaign_id=self.campaign.pk,
                     salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_campaign_audience_csv(self.campaign))
        self.assertIn("in@example.com", out.getvalue())
        self.assertNotIn("out@example.com", out.getvalue())

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audience.csv")
            call_command("export_campaign_audience",
                         campaign_id=self.campaign.pk,
                         salon_id=self.salon.pk, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(written,
                         export_campaign_audience_csv(self.campaign))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_campaign_audience",
                         campaign_id=self.campaign.pk,
                         salon_id=self.salon.pk + 1000,
                         stdout=io.StringIO())

    def test_unknown_campaign_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_campaign_audience",
                         campaign_id=self.campaign.pk + 1000,
                         salon_id=self.salon.pk, stdout=io.StringIO())

    def test_campaign_of_another_salon_raises(self):
        foreign = Campaign.objects.create(
            salon=self.other, name="Elsewhere", channel="sms",
            body="Elsewhere")
        with self.assertRaises(CommandError):
            call_command("export_campaign_audience",
                         campaign_id=foreign.pk,
                         salon_id=self.salon.pk, stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.csv")
            with self.assertRaises(CommandError):
                call_command("export_campaign_audience",
                             campaign_id=self.campaign.pk,
                             salon_id=self.salon.pk, output=path,
                             stdout=io.StringIO())

    def test_read_only_no_sends_created(self):
        from messaging.models import CampaignSend
        call_command("export_campaign_audience",
                     campaign_id=self.campaign.pk,
                     salon_id=self.salon.pk, stdout=io.StringIO())
        self.assertEqual(CampaignSend.objects.count(), 0)
        self.assertEqual(Campaign.objects.count(), 1)
