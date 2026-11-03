"""export_campaigns command: thin wrapper over campaign_export."""
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from messaging.campaign_export import export_campaigns_csv
from messaging.models import Campaign
from saloncore.models import Salon


class ExportCampaignsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        Campaign.objects.create(
            salon=self.salon, name="Spring Offer",
            channel="sms", body="Hello body")
        Campaign.objects.create(
            salon=self.salon, name="Spring Email",
            channel="email", subject="Hi", body="Email body")
        Campaign.objects.create(
            salon=self.other, name="Other Campaign",
            channel="sms", body="Elsewhere")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_campaigns_csv(self.salon))
        self.assertIn("Hello body", out.getvalue())
        self.assertIn("updated_at", out.getvalue().splitlines()[0])

    def test_salon_scoping(self):
        out = io.StringIO()
        call_command("export_campaigns", salon_id=self.other.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_campaigns_csv(self.other))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)
        self.assertNotIn("Spring Offer", out.getvalue())

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "campaigns.csv")
            call_command("export_campaigns", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(written, export_campaigns_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_campaigns",
                         salon_id=self.salon.pk + 1000,
                         stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.csv")
            with self.assertRaises(CommandError):
                call_command("export_campaigns", salon_id=self.salon.pk,
                             output=path, stdout=io.StringIO())
