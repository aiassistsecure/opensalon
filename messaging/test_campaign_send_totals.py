from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import TestCase

from clients.models import Client
from messaging.campaign_send_totals import (
    campaign_send_totals,
    per_channel_campaign_send_totals,
)
from messaging.models import Campaign, CampaignSend
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)
DAY3 = date(2026, 3, 4)


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


class CampaignSendTotalsBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self._n = 0

    def _send(self, salon, channel, when, status="sent"):
        self._n += 1
        client = Client.objects.create(
            salon=salon, first_name=f"C{self._n}", last_name="Example",
            email=f"c{self._n}@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True,
        )
        campaign = Campaign.objects.create(
            salon=salon, name=f"Campaign {self._n}", channel=channel,
            body="Hello", status=Campaign.Status.SENT, sent_at=when,
        )
        return CampaignSend.objects.create(
            campaign=campaign, client=client, channel=channel,
            status=status, sent_at=when,
        )

    def _own(self, channel, when, status="sent"):
        return self._send(self.salon, channel, when, status)


class GroupingTests(CampaignSendTotalsBase):
    def test_channel_and_status_grouping(self):
        self._own("email", _at(DAY1, 9))
        self._own("email", _at(DAY1, 10))
        self._own("sms", _at(DAY2, 9))
        result = campaign_send_totals(self.salon, DAY1, DAY3)
        self.assertEqual(result.total, 3)
        self.assertEqual(result.salon, self.salon)
        self.assertEqual(result.by_channel, {"sms": 1, "email": 2})
        # Only status that exists on CampaignSend is "sent".
        self.assertEqual(result.by_status, {"sent": 3})
        self.assertEqual(result.status_count("sent"), 3)
        self.assertEqual(
            result.by_channel_by_status,
            {"sms": {"sent": 1}, "email": {"sent": 2}},
        )
        self.assertEqual(result.count_for("sms"), 1)
        self.assertEqual(per_channel_campaign_send_totals(
            self.salon, DAY1, DAY3).total, 3)

    def test_per_day_zero_filled(self):
        self._own("email", _at(DAY1, 9))
        self._own("sms", _at(DAY1, 23))
        self._own("sms", _at(DAY3, 1))
        result = campaign_send_totals(self.salon, DAY1, DAY3)
        self.assertEqual(result.by_day, {DAY1: 2, DAY2: 0, DAY3: 1})
        self.assertEqual(result.by_date, result.by_day)
        self.assertEqual(
            result.by_day_by_channel[DAY2], {"sms": 0, "email": 0})
        self.assertEqual(
            result.by_day_by_channel[DAY1], {"sms": 1, "email": 1})

    def test_local_day_uses_salon_timezone(self):
        ny = Salon.objects.create(name="NY Salon", timezone="America/New_York")
        # 01:00 UTC on DAY2 is 20:00 on DAY1 in America/New_York.
        self._send(ny, "email", _at(DAY2, 1))
        result = campaign_send_totals(ny, DAY1, DAY2)
        self.assertEqual(result.by_day, {DAY1: 1, DAY2: 0})


class RangeAndScopeTests(CampaignSendTotalsBase):
    def test_range_boundaries_inclusive_whole_days(self):
        self._own("email", _at(DAY1, 0))
        self._own("email", _at(DAY2, 23))
        self._own("email", _at(DAY3, 0))
        result = campaign_send_totals(
            self.salon, date_from=DAY1, date_to=DAY2)
        self.assertEqual(result.total, 2)
        self.assertEqual((result.start_date, result.end_date), (DAY1, DAY2))
        single = campaign_send_totals(self.salon, DAY2, DAY2)
        self.assertEqual(single.by_day, {DAY2: 1})

    def test_other_salon_excluded(self):
        self._own("email", _at(DAY1, 9))
        self._send(self.other, "email", _at(DAY1, 9))
        self._send(self.other, "sms", _at(DAY1, 10))
        result = campaign_send_totals(self.salon, DAY1, DAY3)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.by_channel, {"sms": 0, "email": 1})
        self.assertEqual(
            campaign_send_totals(self.other, DAY1, DAY3).total, 2)

    def test_reversed_range_raises(self):
        with self.assertRaises(ValueError):
            campaign_send_totals(self.salon, DAY3, DAY1)


class EmptyAndReadOnlyTests(CampaignSendTotalsBase):
    def test_empty_range_zeroed_not_none(self):
        result = campaign_send_totals(self.salon, DAY1, DAY3)
        self.assertIsNotNone(result)
        self.assertEqual(result.total, 0)
        self.assertEqual(result.by_channel, {"sms": 0, "email": 0})
        self.assertEqual(result.by_status, {"sent": 0})
        self.assertEqual(result.by_day, {DAY1: 0, DAY2: 0, DAY3: 0})
        self.assertEqual(result.as_dict()["by_day"][DAY2], 0)
        self.assertEqual(campaign_send_totals(None, DAY1, DAY2).total, 0)

    def test_read_only_no_mutation_no_new_rows(self):
        row = self._own("email", _at(DAY1, 9))
        before = CampaignSend.objects.count()
        snapshot = (row.channel, row.status, row.sent_at, row.detail)
        campaign_send_totals(self.salon, DAY1, DAY3)
        campaign_send_totals(self.salon, DAY1, DAY3)
        self.assertEqual(CampaignSend.objects.count(), before)
        row.refresh_from_db()
        self.assertEqual(
            (row.channel, row.status, row.sent_at, row.detail), snapshot)
