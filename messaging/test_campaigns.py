from django.core.exceptions import ValidationError
from django.test import TestCase

from clients.models import Client
from messaging import campaigns as campaigns_module
from messaging.campaigns import (
    audience_count,
    audience_for,
    audience_queryset,
    audience_summary,
)
from messaging.models import Campaign
from saloncore.models import Salon


class CampaignTests(TestCase):
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
            sms_opt_in=False, email_opt_in=False, active=True,
        )
        defaults.update(kwargs)
        return Client.objects.create(**defaults)

    def _campaign(self, salon=None, **kwargs):
        defaults = dict(
            salon=salon or self.salon, name="Spring Offer",
            channel=Campaign.Channel.SMS, subject="", body="Hello",
        )
        defaults.update(kwargs)
        return Campaign.objects.create(**defaults)

    def test_creation_defaults_to_draft_and_scopes_to_salon(self):
        campaign = self._campaign()
        self.assertEqual(campaign.status, Campaign.Status.DRAFT)
        self.assertEqual(campaign.salon, self.salon)
        self.assertEqual(list(self.salon.campaigns.all()), [campaign])
        self.assertEqual(list(self.other.campaigns.all()), [])
        email = self._campaign(
            name="News", channel=Campaign.Channel.EMAIL,
            subject="News", body="Body",
        )
        self.assertEqual(email.channel, "email")
        self.assertEqual(email.subject, "News")

    def test_sms_audience_respects_sms_opt_in_exactly(self):
        both = self._client(sms_opt_in=True, email_opt_in=True)
        sms_only = self._client(sms_opt_in=True, email_opt_in=False)
        self._client(sms_opt_in=False, email_opt_in=True)
        self._client(sms_opt_in=False, email_opt_in=False)
        campaign = self._campaign(channel=Campaign.Channel.SMS)
        self.assertEqual(
            set(audience_queryset(campaign)), {both, sms_only}
        )
        self.assertEqual(audience_count(campaign), 2)

    def test_email_audience_respects_email_opt_in_exactly(self):
        both = self._client(sms_opt_in=True, email_opt_in=True)
        email_only = self._client(sms_opt_in=False, email_opt_in=True)
        self._client(sms_opt_in=True, email_opt_in=False)
        self._client(sms_opt_in=False, email_opt_in=False)
        campaign = self._campaign(
            channel=Campaign.Channel.EMAIL, subject="Hi"
        )
        self.assertEqual(
            set(audience_queryset(campaign)), {both, email_only}
        )
        summary = audience_summary(campaign)
        self.assertEqual(summary.count, 2)
        self.assertEqual(set(summary.client_ids), {both.id, email_only.id})
        self.assertEqual(summary.channel, "email")

    def test_inactive_clients_are_excluded(self):
        self._client(sms_opt_in=True, email_opt_in=True, active=False)
        active = self._client(sms_opt_in=True, email_opt_in=True)
        for channel in (Campaign.Channel.SMS, Campaign.Channel.EMAIL):
            campaign = self._campaign(channel=channel)
            self.assertEqual(list(audience_queryset(campaign)), [active])

    def test_cross_salon_isolation(self):
        mine = self._client(sms_opt_in=True, email_opt_in=True)
        self._client(
            salon=self.other, sms_opt_in=True, email_opt_in=True
        )
        campaign = self._campaign(channel=Campaign.Channel.SMS)
        self.assertEqual(list(audience_queryset(campaign)), [mine])
        other_campaign = self._campaign(
            salon=self.other, channel=Campaign.Channel.SMS
        )
        self.assertEqual(audience_count(other_campaign), 1)
        self.assertNotIn(mine, audience_queryset(other_campaign))
        self.assertEqual(
            list(audience_for(self.salon, "sms")), [mine]
        )

    def test_draft_only_no_send_path(self):
        self.assertEqual(
            [value for value, _ in Campaign.Status.choices], ["draft"]
        )
        campaign = self._campaign()
        campaign.status = "sent"
        with self.assertRaises(ValidationError):
            campaign.save()
        with self.assertRaises(ValidationError):
            Campaign.objects.create(
                salon=self.salon, name="Bad", channel="sms",
                body="x", status="scheduled",
            )
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "draft")
        self.assertFalse(hasattr(campaign, "send"))
        self.assertFalse(hasattr(campaigns_module, "send_campaign"))
        self.assertFalse(hasattr(campaigns_module, "dispatch_campaign"))

    def test_unknown_channel_rejected(self):
        with self.assertRaises(ValidationError):
            audience_for(self.salon, "pigeon")
