"""Tests for the send_campaign management command.

The command is a thin wrapper around
``messaging.campaign_send.send_campaign``: these tests pin
that the real run delegates (sends, writes CampaignSend
rows, transitions the campaign to sent, reports the
summary), and that ``--dry-run`` re-resolves the audience
exactly as the real send does, prints counts by channel
(would-send / skipped by opt-in / skipped missing
contact), sends nothing, writes no CampaignSend rows, and
leaves the campaign a draft. Output is counts only.
"""
import io
from unittest import mock

from django.core import mail
from django.core.management import CommandError, call_command, get_commands
from django.test import TestCase, override_settings

from clients.models import Client
from messaging.adapters import SmsResult
from messaging.models import Campaign, CampaignSend
from saloncore.models import Salon


class RecordingSmsAdapter:
    name = "recording"

    def __init__(self, success=True):
        self.calls = []
        self.success = success

    def send_sms(self, to, body):
        self.calls.append((to, body))
        return SmsResult(
            success=self.success,
            status="sent" if self.success else "failed",
            reference="ref-1" if self.success else "",
        )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="salon@example.com",
)
class SendCampaignCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Salon One")
        self.other = Salon.objects.create(name="Salon Two")
        self._n = 0
        self.adapter = RecordingSmsAdapter()

    def _client(self, salon=None, **kwargs):
        self._n += 1
        defaults = dict(
            salon=salon or self.salon, first_name=f"C{self._n}",
            last_name="Example", phone=f"555-010{self._n}",
            email=f"c{self._n}@example.com",
            sms_opt_in=False, email_opt_in=False, active=True,
        )
        defaults.update(kwargs)
        return Client.objects.create(**defaults)

    def _campaign(self, **kwargs):
        defaults = dict(
            salon=self.salon, name="Spring Offer",
            channel=Campaign.Channel.SMS, subject="", body="Hello",
        )
        defaults.update(kwargs)
        return Campaign.objects.create(**defaults)

    def _run(self, campaign_id, *extra):
        out = io.StringIO()
        with mock.patch(
                "messaging.campaign_send.get_sms_adapter",
                return_value=self.adapter):
            call_command(
                "send_campaign", "--campaign-id", str(campaign_id),
                *extra, stdout=out)
        return out.getvalue()

    def test_command_registered(self):
        self.assertIn("send_campaign", get_commands())

    def test_sms_dry_run_counts_and_sends_nothing(self):
        self._client(sms_opt_in=True)                    # would send
        self._client(sms_opt_in=True, phone="")          # missing contact
        self._client(sms_opt_in=False)                   # skipped opt-in
        self._client(sms_opt_in=True, active=False)      # excluded entirely
        self._client(salon=self.other, sms_opt_in=True)  # other salon
        campaign = self._campaign()
        text = self._run(campaign.pk, "--dry-run")
        self.assertIn("Dry run", text)
        self.assertIn("(sms)", text)
        self.assertIn("1 would send", text)
        self.assertIn("1 skipped by opt-in", text)
        self.assertIn("1 skipped missing contact", text)
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(CampaignSend.objects.count(), 0)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.DRAFT)
        self.assertIsNone(campaign.sent_at)

    def test_email_dry_run_counts_and_sends_nothing(self):
        self._client(email_opt_in=True)                  # would send
        self._client(email_opt_in=True, email="")        # missing contact
        self._client(email_opt_in=False)                 # skipped opt-in
        campaign = self._campaign(
            channel=Campaign.Channel.EMAIL, subject="News", body="Body")
        text = self._run(campaign.pk, "--dry-run")
        self.assertIn("Dry run", text)
        self.assertIn("(email)", text)
        self.assertIn("1 would send", text)
        self.assertIn("1 skipped by opt-in", text)
        self.assertIn("1 skipped missing contact", text)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(CampaignSend.objects.count(), 0)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.DRAFT)

    def test_sms_real_run_sends_and_reports_summary(self):
        reachable = self._client(sms_opt_in=True)
        self._client(sms_opt_in=True, phone="")
        self._client(sms_opt_in=False)
        campaign = self._campaign(body="Sale this week")
        text = self._run(campaign.pk)
        self.assertNotIn("Dry run", text)
        self.assertIn("1 sent", text)
        self.assertIn("1 skipped", text)
        self.assertIn("1 skipped missing contact", text)
        self.assertEqual(
            self.adapter.calls, [(reachable.phone, "Sale this week")])
        rows = CampaignSend.objects.filter(campaign=campaign)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().client_id, reachable.id)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.SENT)
        self.assertIsNotNone(campaign.sent_at)

    def test_email_real_run_sends_and_reports_summary(self):
        self._client(email_opt_in=True)
        self._client(sms_opt_in=True, email_opt_in=False)
        campaign = self._campaign(
            channel=Campaign.Channel.EMAIL, subject="News", body="Body")
        text = self._run(campaign.pk)
        self.assertIn("1 sent", text)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "News")
        self.assertEqual(CampaignSend.objects.count(), 1)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.SENT)

    def test_unknown_campaign_id_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._run(999999)
        with self.assertRaises(CommandError):
            self._run(999999, "--dry-run")

    def test_non_draft_campaign_refused_on_both_paths(self):
        self._client(sms_opt_in=True)
        campaign = self._campaign()
        self._run(campaign.pk)
        self.assertEqual(CampaignSend.objects.count(), 1)
        with self.assertRaises(CommandError):
            self._run(campaign.pk)
        with self.assertRaises(CommandError):
            self._run(campaign.pk, "--dry-run")
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(CampaignSend.objects.count(), 1)
