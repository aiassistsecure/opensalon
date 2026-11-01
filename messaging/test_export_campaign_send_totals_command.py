"""Tests for the export_campaign_send_totals management command.

The command is a thin wrapper around
``messaging.campaign_send_totals_export.export_campaign_send_totals_summary_csv``:
these tests pin that its stdout and file output match that
service verbatim, that salon scoping is honoured, and that
unknown salons and unwritable outputs fail cleanly as
``CommandError``.
"""
import io
import os
import tempfile
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client
from messaging.campaign_send_totals_export import (
    export_campaign_send_totals_summary_csv,
)
from messaging.models import Campaign, CampaignSend
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)
DAY3 = date(2026, 3, 4)


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


class ExportCampaignSendTotalsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self._n = 0
        self._send(self.salon, "email", _at(DAY1, 9))
        self._send(self.salon, "sms", _at(DAY2, 9))
        self._send(self.other, "email", _at(DAY1, 9))

    def _send(self, salon, channel, when, status="sent"):
        self._n += 1
        client = Client.objects.create(
            salon=salon, first_name=f"C{self._n}", last_name="Example",
            email=f"c{self._n}@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        campaign = Campaign.objects.create(
            salon=salon, name=f"Campaign {self._n}", channel=channel,
            body="Hello", status=Campaign.Status.SENT, sent_at=when)
        return CampaignSend.objects.create(
            campaign=campaign, client=client, channel=channel,
            status=status, sent_at=when)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_campaign_send_totals",
                     salon_id=self.salon.pk, date_from=DAY1,
                     date_to=DAY3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_campaign_send_totals_summary_csv(self.salon, DAY1, DAY3))

    def test_stdout_matches_service_single_day(self):
        out = io.StringIO()
        call_command("export_campaign_send_totals",
                     salon_id=self.salon.pk, date_from=DAY1, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_campaign_send_totals_summary_csv(self.salon, DAY1))

    def test_stdout_matches_service_with_cli_args(self):
        out = io.StringIO()
        call_command(
            "export_campaign_send_totals", "--salon-id", str(self.salon.pk),
            "--date-from", DAY1.isoformat(),
            "--date-to", DAY3.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_campaign_send_totals_summary_csv(self.salon, DAY1, DAY3))

    def test_stdout_matches_service_with_alias_kwargs(self):
        out = io.StringIO()
        call_command("export_campaign_send_totals",
                     salon_id=self.salon.pk, start=DAY1, end=DAY2,
                     stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_campaign_send_totals_summary_csv(self.salon, DAY1, DAY2))

    def test_salon_scoping(self):
        out = io.StringIO()
        call_command("export_campaign_send_totals",
                     salon_id=self.salon.pk, date_from=DAY1,
                     date_to=DAY3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_campaign_send_totals_summary_csv(self.salon, DAY1, DAY3))
        self.assertIn("email,sent,1", out.getvalue())
        other_out = io.StringIO()
        call_command("export_campaign_send_totals",
                     salon_id=self.other.pk, date_from=DAY1,
                     date_to=DAY3, stdout=other_out)
        self.assertEqual(
            other_out.getvalue(),
            export_campaign_send_totals_summary_csv(self.other, DAY1, DAY3))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "campaign_send_totals.csv")
            call_command("export_campaign_send_totals",
                         salon_id=self.salon.pk, date_from=DAY1,
                         date_to=DAY3, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            written,
            export_campaign_send_totals_summary_csv(self.salon, DAY1, DAY3))
        self.assertEqual(out.getvalue(), "")

    def test_reversed_range_matches_service_verbatim(self):
        out = io.StringIO()
        call_command("export_campaign_send_totals",
                     salon_id=self.salon.pk, date_from=DAY3,
                     date_to=DAY1, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_campaign_send_totals_summary_csv(self.salon, DAY3, DAY1))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_campaign_send_totals",
                         salon_id=self.salon.pk + 1000, date_from=DAY1,
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "totals.csv")
            with self.assertRaises(CommandError):
                call_command("export_campaign_send_totals",
                             salon_id=self.salon.pk, date_from=DAY1,
                             output=path, stdout=io.StringIO())
