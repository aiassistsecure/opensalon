"""Tests for --now on the send_campaign command.

``--now`` pins the instant stamped as the campaign's
``sent_at``: it is parsed from ISO-8601 to an aware datetime
and passed through to the existing service (``now=``), so a
run can be replayed for a chosen instant. When omitted, the
service's own default applies -- today's clock, exactly as
before this flag existed. The service's ``adapter``
parameter stays excluded -- dependency injection, not an
operator flag.
"""
import datetime
import io
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from clients.models import Client
from messaging.adapters import SmsResult
from messaging.campaign_send import CampaignSendSummary
from messaging.models import Campaign, CampaignSend
from saloncore.models import Salon


class RecordingSmsAdapter:
    name = "recording"

    def __init__(self):
        self.calls = []

    def send_sms(self, to, body):
        self.calls.append((to, body))
        return SmsResult(success=True, status="sent", reference="ref-1")


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="salon@example.com",
)
class SendCampaignNowCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Salon One")
        Client.objects.create(
            salon=self.salon, first_name="C1", last_name="Example",
            phone="555-0100", email="c1@example.com",
            sms_opt_in=True, active=True)
        self.adapter = RecordingSmsAdapter()
        self.ref = timezone.now()

    def _campaign(self):
        return Campaign.objects.create(
            salon=self.salon, name="Spring Offer",
            channel=Campaign.Channel.SMS, subject="", body="Hello")

    def _run(self, campaign_id, *extra_args, **kwargs):
        out = io.StringIO()
        with mock.patch(
                "messaging.campaign_send.get_sms_adapter",
                return_value=self.adapter):
            call_command(
                "send_campaign", "--campaign-id", str(campaign_id),
                *extra_args, stdout=out, **kwargs)
        return out.getvalue()

    # -- behaviour: the pinned instant stamps sent_at ---------

    def test_now_stamps_sent_at_exactly(self):
        campaign = self._campaign()
        text = self._run(campaign.pk, "--now", self.ref.isoformat())
        self.assertIn("1 sent", text)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.SENT)
        self.assertEqual(campaign.sent_at, self.ref)
        self.assertEqual(CampaignSend.objects.count(), 1)

    def test_omitted_now_uses_todays_clock(self):
        campaign = self._campaign()
        before = timezone.now()
        self._run(campaign.pk)
        after = timezone.now()
        campaign.refresh_from_db()
        self.assertIsNotNone(campaign.sent_at)
        self.assertLessEqual(before, campaign.sent_at)
        self.assertLessEqual(campaign.sent_at, after)

    def test_now_z_suffix_is_aware_equivalent(self):
        campaign = self._campaign()
        zulu = self.ref.astimezone(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        self._run(campaign.pk, "--now", zulu)
        campaign.refresh_from_db()
        self.assertEqual(
            campaign.sent_at, self.ref.replace(microsecond=0))

    def test_now_kwargs_datetime_and_string_match_cli(self):
        for value in (self.ref, self.ref.isoformat()):
            campaign = self._campaign()
            self._run(campaign.pk, now=value)
            campaign.refresh_from_db()
            self.assertEqual(campaign.sent_at, self.ref)

    def test_now_with_dry_run_sends_nothing_and_stays_draft(self):
        campaign = self._campaign()
        text = self._run(
            campaign.pk, "--now", self.ref.isoformat(), "--dry-run")
        self.assertIn("Dry run", text)
        self.assertIn("1 would send", text)
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(CampaignSend.objects.count(), 0)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.DRAFT)
        self.assertIsNone(campaign.sent_at)

    # -- passthrough: the service receives the parsed instant --

    def test_service_receives_parsed_aware_now(self):
        campaign = self._campaign()
        target = ("messaging.management.commands.send_campaign"
                  ".send_campaign")
        summary = CampaignSendSummary(
            campaign_id=campaign.pk, channel="sms", sent=1)
        with mock.patch(target, return_value=summary) as svc:
            call_command(
                "send_campaign", "--campaign-id", str(campaign.pk),
                "--now", self.ref.isoformat(), stdout=io.StringIO())
        self.assertEqual(svc.call_args.args[0].pk, campaign.pk)
        self.assertEqual(svc.call_args.kwargs["now"], self.ref)
        self.assertIsNotNone(svc.call_args.kwargs["now"].tzinfo)
        self.assertNotIn("adapter", svc.call_args.kwargs)

    def test_service_receives_none_when_omitted(self):
        campaign = self._campaign()
        target = ("messaging.management.commands.send_campaign"
                  ".send_campaign")
        summary = CampaignSendSummary(
            campaign_id=campaign.pk, channel="sms", sent=1)
        with mock.patch(target, return_value=summary) as svc:
            call_command(
                "send_campaign", "--campaign-id", str(campaign.pk),
                stdout=io.StringIO())
        self.assertIsNone(svc.call_args.kwargs["now"])

    # -- invalid input -------------------------------------------

    def test_bad_now_raises_command_error(self):
        campaign = self._campaign()
        with self.assertRaises(CommandError):
            self._run(campaign.pk, "--now", "not-a-datetime")
        with self.assertRaises(CommandError):
            self._run(campaign.pk, now="not-a-datetime")
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.DRAFT)
