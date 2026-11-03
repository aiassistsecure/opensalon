"""Tests for the discard_campaign service + command.

The command is a thin wrapper around
``messaging.campaigns.discard_campaign``: these tests pin
that a real run deletes exactly the named DRAFT campaign
through that service, that ``--dry-run`` deletes nothing
but prints the draft's audience count, and that a SENT
campaign is refused on both layers (service
``ValidationError``, command ``CommandError``) with its
``CampaignSend`` history untouched. An unknown id surfaces
as ``CommandError``. Fixtures are tiny synthetic records --
unit logic only.
"""
import io

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command, get_commands
from django.test import TestCase
from django.utils import timezone

from clients.models import Client
from messaging.campaigns import discard_campaign
from messaging.models import Campaign, CampaignSend
from saloncore.models import Salon


class DiscardCampaignTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Salon One")
        self.other = Salon.objects.create(name="Salon Two")
        self._n = 0

    def _client(self, salon=None, **kwargs):
        self._n += 1
        defaults = dict(
            salon=salon or self.salon, first_name=f"C{self._n}",
            last_name="Example", phone="555-0100",
            email=f"c{self._n}@example.com",
            sms_opt_in=False, email_opt_in=False, active=True)
        defaults.update(kwargs)
        return Client.objects.create(**defaults)

    def _campaign(self, salon=None, **kwargs):
        defaults = dict(
            salon=salon or self.salon, name="Spring Offer",
            channel=Campaign.Channel.SMS, subject="", body="Hello")
        defaults.update(kwargs)
        return Campaign.objects.create(**defaults)

    def _sent_campaign(self):
        campaign = self._campaign(
            status=Campaign.Status.SENT, sent_at=timezone.now())
        client = self._client(sms_opt_in=True)
        CampaignSend.record(campaign, client, detail="ref-1")
        return campaign

    def _run(self, *args, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("stdout", out)
        call_command("discard_campaign", *args, **kwargs)
        return out.getvalue()

    def test_command_registered(self):
        self.assertIn("discard_campaign", get_commands())

    def test_service_discards_draft_and_returns_summary(self):
        self._client(sms_opt_in=True)
        self._client(sms_opt_in=True)
        self._client(email_opt_in=True)  # not sms audience
        campaign = self._campaign()
        campaign_id = campaign.pk
        summary = discard_campaign(campaign)
        self.assertEqual(summary.campaign_id, campaign_id)
        self.assertEqual(summary.name, "Spring Offer")
        self.assertEqual(summary.channel, Campaign.Channel.SMS)
        self.assertEqual(summary.audience_count, 2)
        self.assertEqual(Campaign.objects.count(), 0)

    def test_service_discards_only_the_named_draft(self):
        keep = self._campaign(name="Keep Me")
        drop = self._campaign(name="Drop Me")
        other_salon_draft = self._campaign(salon=self.other, name="Other")
        discard_campaign(drop)
        self.assertEqual(
            set(Campaign.objects.all()), {keep, other_salon_draft})

    def test_service_refuses_sent_and_preserves_sends(self):
        campaign = self._sent_campaign()
        with self.assertRaises(ValidationError):
            discard_campaign(campaign)
        self.assertTrue(Campaign.objects.filter(pk=campaign.pk).exists())
        self.assertEqual(CampaignSend.objects.count(), 1)
        self.assertEqual(
            CampaignSend.objects.get().campaign_id, campaign.pk)

    def test_service_refuses_unsaved_campaign(self):
        with self.assertRaises(ValidationError):
            discard_campaign(Campaign(
                salon=self.salon, name="Unsaved",
                channel=Campaign.Channel.SMS, body="Hi"))
        with self.assertRaises(ValidationError):
            discard_campaign(None)
        self.assertEqual(Campaign.objects.count(), 0)

    def test_command_real_run_deletes_draft(self):
        self._client(sms_opt_in=True)
        campaign = self._campaign()
        campaign_id = campaign.pk
        text = self._run(campaign_id=campaign_id)
        self.assertEqual(Campaign.objects.count(), 0)
        self.assertIn("Discarded draft campaign", text)
        self.assertIn(str(campaign_id), text)
        self.assertIn("audience 1", text)

    def test_command_dry_run_deletes_nothing_prints_audience(self):
        self._client(sms_opt_in=True)
        self._client(sms_opt_in=True, email_opt_in=True)
        self._client(email_opt_in=True)               # not sms audience
        self._client(sms_opt_in=True, active=False)   # inactive excluded
        self._client(salon=self.other, sms_opt_in=True)  # other salon
        campaign = self._campaign()
        text = self._run(
            "--campaign-id", str(campaign.pk), "--dry-run")
        self.assertEqual(Campaign.objects.count(), 1)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.DRAFT)
        self.assertIn("Dry run", text)
        self.assertIn("audience 2", text)
        self.assertIn("no campaign deleted", text)

    def test_command_refuses_sent_on_both_paths(self):
        campaign = self._sent_campaign()
        for extra in ({}, {"dry_run": True}):
            with self.assertRaises(CommandError):
                self._run(campaign_id=campaign.pk, **extra)
        self.assertTrue(Campaign.objects.filter(pk=campaign.pk).exists())
        self.assertEqual(CampaignSend.objects.count(), 1)

    def test_command_unknown_id_is_error(self):
        for extra in ({}, {"dry_run": True}):
            with self.assertRaises(CommandError):
                self._run(campaign_id=999999, **extra)
        self.assertEqual(Campaign.objects.count(), 0)
