from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from clients.models import Client
from messaging.adapters import SmsResult
from messaging.campaign_send import send_campaign
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
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
)
class CampaignSendTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Salon One")
        self.other = Salon.objects.create(name="Salon Two")
        self._n = 0

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

    def test_sms_send_delivers_opt_in_only_and_logs_rows(self):
        both = self._client(sms_opt_in=True, email_opt_in=True)
        sms_only = self._client(sms_opt_in=True, email_opt_in=False)
        self._client(sms_opt_in=False, email_opt_in=True)
        self._client(sms_opt_in=True, active=False)
        self._client(salon=self.other, sms_opt_in=True)
        campaign = self._campaign(body="Sale this week")
        adapter = RecordingSmsAdapter()
        summary = send_campaign(campaign, adapter=adapter)
        self.assertEqual(
            {to for to, _ in adapter.calls}, {both.phone, sms_only.phone}
        )
        self.assertTrue(all(b == "Sale this week" for _, b in adapter.calls))
        self.assertEqual(summary.sent, 2)
        self.assertEqual(set(summary.sent_client_ids), {both.id, sms_only.id})
        rows = CampaignSend.objects.filter(campaign=campaign)
        self.assertEqual(rows.count(), 2)
        self.assertEqual({r.client_id for r in rows}, {both.id, sms_only.id})
        self.assertTrue(all(r.channel == "sms" and r.detail == "ref-1"
                              for r in rows))
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.SENT)
        self.assertIsNotNone(campaign.sent_at)

    def test_email_send_delivers_email_opt_in_only_and_logs_rows(self):
        both = self._client(sms_opt_in=True, email_opt_in=True)
        email_only = self._client(sms_opt_in=False, email_opt_in=True)
        self._client(sms_opt_in=True, email_opt_in=False)
        campaign = self._campaign(
            channel=Campaign.Channel.EMAIL, subject="News", body="Body text",
        )
        summary = send_campaign(campaign)
        self.assertEqual(
            {m.to[0] for m in mail.outbox}, {both.email, email_only.email}
        )
        self.assertTrue(all(m.subject == "News" for m in mail.outbox))
        self.assertTrue(all(m.body == "Body text" for m in mail.outbox))
        self.assertEqual(summary.sent, 2)
        rows = CampaignSend.objects.filter(campaign=campaign)
        self.assertEqual({r.client_id for r in rows}, {both.id, email_only.id})
        self.assertTrue(all(r.channel == "email" for r in rows))
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.SENT)
        self.assertIsNotNone(campaign.sent_at)

    def test_opt_out_after_preview_is_excluded_at_send_time(self):
        stays = self._client(sms_opt_in=True)
        leaves = self._client(sms_opt_in=True)
        campaign = self._campaign()
        # Client opts out after the draft/preview, before the send.
        leaves.sms_opt_in = False
        leaves.save()
        adapter = RecordingSmsAdapter()
        summary = send_campaign(campaign, adapter=adapter)
        self.assertEqual([to for to, _ in adapter.calls], [stays.phone])
        self.assertEqual(summary.sent_client_ids, [stays.id])
        self.assertFalse(
            CampaignSend.objects.filter(client=leaves).exists()
        )

    def test_resend_refused(self):
        self._client(sms_opt_in=True)
        campaign = self._campaign()
        adapter = RecordingSmsAdapter()
        send_campaign(campaign, adapter=adapter)
        with self.assertRaises(ValidationError):
            send_campaign(campaign, adapter=adapter)
        # A fresh copy from the DB is refused too, and nothing re-sends.
        with self.assertRaises(ValidationError):
            send_campaign(
                Campaign.objects.get(pk=campaign.pk), adapter=adapter
            )
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(CampaignSend.objects.count(), 1)

    def test_missing_contact_and_failed_send_are_skipped_not_logged(self):
        no_phone = self._client(sms_opt_in=True, phone="")
        campaign = self._campaign()
        summary = send_campaign(campaign, adapter=RecordingSmsAdapter())
        self.assertEqual(summary.sent, 0)
        self.assertEqual(summary.skipped_missing_contact, 1)
        self.assertFalse(CampaignSend.objects.exists())
        self.assertEqual(no_phone.campaign_sends.count(), 0)
        campaign2 = self._campaign(name="Second")
        self._client(sms_opt_in=True)
        summary2 = send_campaign(
            campaign2, adapter=RecordingSmsAdapter(success=False)
        )
        self.assertEqual(summary2.sent, 0)
        self.assertEqual(summary2.skipped_send_failed, 1)
        self.assertFalse(
            CampaignSend.objects.filter(campaign=campaign2).exists()
        )

    def test_duplicate_campaign_client_send_rejected(self):
        client = self._client(sms_opt_in=True)
        campaign = self._campaign()
        CampaignSend.record(campaign, client)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CampaignSend.record(campaign, client)
        self.assertEqual(CampaignSend.objects.count(), 1)

    def test_unsaved_campaign_refused(self):
        with self.assertRaises(ValidationError):
            send_campaign(
                Campaign(salon=self.salon, name="X", channel="sms"),
                adapter=RecordingSmsAdapter(),
            )
