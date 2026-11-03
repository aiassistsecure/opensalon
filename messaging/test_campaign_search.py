import csv
import io
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from clients.models import Client
from messaging.campaign_search import campaign_search, search_campaigns
from messaging.campaign_search_export import (
    EXPORT_FIELDNAMES,
    export_campaign_search,
    export_campaign_search_csv,
)
from messaging.models import Campaign, CampaignSend
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)
DAY3 = date(2026, 3, 4)


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


class CampaignSearchBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self._n = 0

    def _campaign(self, name="Spring Offer", salon=None, created=None,
                  **kwargs):
        defaults = dict(
            salon=salon or self.salon, name=name,
            channel=Campaign.Channel.SMS, subject="", body="Hello",
        )
        defaults.update(kwargs)
        campaign = Campaign.objects.create(**defaults)
        if created is not None:
            Campaign.objects.filter(pk=campaign.pk).update(
                created_at=created)
            campaign.refresh_from_db()
        return campaign

    def _send(self, campaign, n=1):
        for _ in range(n):
            self._n += 1
            client = Client.objects.create(
                salon=campaign.salon, first_name=f"C{self._n}",
                last_name="Example", email=f"c{self._n}@example.com",
                phone="555-0100", sms_opt_in=True, email_opt_in=True)
            CampaignSend.objects.create(
                campaign=campaign, client=client,
                channel=campaign.channel, status="sent",
                sent_at=timezone.now())


class SearchTests(CampaignSearchBase):
    def test_only_own_salon_and_none_salon(self):
        own = self._campaign()
        self._campaign(salon=self.other)
        self.assertEqual([c.id for c in search_campaigns(self.salon)], [own.id])
        self.assertEqual(search_campaigns(None), [])

    def test_name_fragment_case_insensitive_and_blank(self):
        hit = self._campaign(name="Spring Offer")
        self._campaign(name="Winter News")
        self.assertEqual(
            [c.id for c in search_campaigns(self.salon, "spring")], [hit.id])
        self.assertEqual(
            [c.id for c in campaign_search(self.salon, "SPRING")], [hit.id])
        self.assertEqual(search_campaigns(self.salon, "zzz"), [])
        self.assertEqual(len(search_campaigns(self.salon, "  ")), 2)
        self.assertEqual(len(search_campaigns(self.salon)), 2)

    def test_status_and_channel_filters_combine(self):
        hit = self._campaign(name="A", status="draft", channel="sms")
        self._campaign(name="A2", channel="email",
                       status="sent", sent_at=_at(DAY1))
        self.assertEqual(
            [c.id for c in search_campaigns(self.salon, status="draft")],
            [hit.id])
        self.assertEqual(len(search_campaigns(
            self.salon, channel="email")), 1)
        self.assertEqual(search_campaigns(
            self.salon, status="draft", channel="email"), [])

    def test_date_window_on_created_at_inclusive(self):
        self._campaign(name="Old", created=_at(DAY1))
        mid = self._campaign(name="Mid", created=_at(DAY2, 23))
        self._campaign(name="New", created=_at(DAY3))
        self.assertEqual(
            [c.id for c in search_campaigns(
                self.salon, start=DAY2, end=DAY2)], [mid.id])
        self.assertEqual(len(search_campaigns(
            self.salon, date_from=DAY1, date_to=DAY2)), 2)
        self.assertEqual(len(search_campaigns(self.salon, start=DAY2)), 2)
        with self.assertRaises(ValueError):
            search_campaigns(self.salon, start=DAY3, end=DAY1)

    def test_ordering_newest_first_then_id_desc(self):
        oldest = self._campaign(name="Old", created=_at(DAY1))
        low = self._campaign(name="Low", created=_at(DAY2))
        high = self._campaign(name="High", created=_at(DAY2))
        self.assertEqual(
            [c.id for c in search_campaigns(self.salon)],
            [high.id, low.id, oldest.id])

    def test_send_count_from_campaign_sends(self):
        busy = self._campaign(name="Busy")
        self._send(busy, n=2)
        quiet = self._campaign(name="Quiet")
        other = self._campaign(name="Other", salon=self.other)
        self._send(other, n=1)
        results = {c.id: c.send_count for c in search_campaigns(self.salon)}
        self.assertEqual(results, {busy.id: 2, quiet.id: 0})

    def test_read_only(self):
        self._campaign()
        before = Campaign.objects.count()
        search_campaigns(self.salon, "spring")
        self.assertEqual(Campaign.objects.count(), before)


class ExportTests(CampaignSearchBase):
    def test_rows_and_csv_agree(self):
        busy = self._campaign(name="Spring Offer", created=_at(DAY1))
        self._send(busy, n=2)
        self._campaign(name="Winter News", created=_at(DAY2))
        rows = export_campaign_search(self.salon, "spring")
        self.assertEqual([r["id"] for r in rows], [busy.id])
        self.assertEqual(list(rows[0]), EXPORT_FIELDNAMES)
        self.assertEqual(rows[0]["send_count"], 2)
        self.assertEqual(rows[0]["salon_id"], self.salon.pk)
        self.assertIsNone(rows[0]["sent_at"])
        text = export_campaign_search_csv(self.salon, "spring")
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual([int(r["id"]) for r in parsed], [busy.id])
        self.assertEqual(parsed[0]["send_count"], "2")

    def test_no_match_none_salon_and_filters(self):
        self._campaign(name="Spring Offer")
        self.assertEqual(export_campaign_search(self.salon, "zzz"), [])
        self.assertEqual(
            export_campaign_search_csv(self.salon, "zzz"),
            ",".join(EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(export_campaign_search(None, "spring"), [])
        self.assertEqual(
            export_campaign_search_csv(None),
            ",".join(EXPORT_FIELDNAMES) + "\n")
        rows = export_campaign_search(self.salon, status="draft")
        self.assertEqual(len(rows), 1)
        with self.assertRaises(ValueError):
            export_campaign_search(self.salon, start=DAY2, end=DAY1)
