import csv
import io
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import TestCase

from clients.models import Client
from messaging.campaign_send_totals import campaign_send_totals
from messaging.campaign_send_totals_export import (
    CAMPAIGN_TOTALS_EXPORT_FIELDNAMES,
    TOTALS_EXPORT_FIELDNAMES,
    campaign_send_totals_export_csv,
    export_campaign_send_totals_summary,
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


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class CampaignSendTotalsExportBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self._n = 0

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

    def _own(self, channel, when):
        return self._send(self.salon, channel, when)


class HeaderTests(CampaignSendTotalsExportBase):
    def test_csv_header_and_row_keys(self):
        self.assertEqual(
            TOTALS_EXPORT_FIELDNAMES, CAMPAIGN_TOTALS_EXPORT_FIELDNAMES)
        text = export_campaign_send_totals_summary_csv(self.salon, DAY1, DAY3)
        self.assertEqual(
            text.splitlines()[0],
            ",".join(CAMPAIGN_TOTALS_EXPORT_FIELDNAMES))
        rows = export_campaign_send_totals_summary(self.salon, DAY1, DAY3)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(list(row), CAMPAIGN_TOTALS_EXPORT_FIELDNAMES)
        parsed = _rows(text)
        self.assertEqual(list(parsed[0]), CAMPAIGN_TOTALS_EXPORT_FIELDNAMES)


class TotalsMatchServiceTests(CampaignSendTotalsExportBase):
    def test_rows_match_campaign_send_totals_verbatim(self):
        self._own("email", _at(DAY1, 9))
        self._own("email", _at(DAY1, 10))
        self._own("sms", _at(DAY2, 9))
        self._send(self.other, "email", _at(DAY1, 9))
        totals = campaign_send_totals(self.salon, DAY1, DAY3)
        rows = export_campaign_send_totals_summary(self.salon, DAY1, DAY3)
        expected = [
            {"salon_id": self.salon.pk,
             "start_date": DAY1.isoformat(), "end_date": DAY3.isoformat(),
             "channel": channel, "status": status,
             "count": totals.by_channel_by_status[channel][status]}
            for channel in ("sms", "email")
            for status in ("sent",)
        ]
        self.assertEqual(rows, expected)
        self.assertEqual(sum(r["count"] for r in rows), totals.total)
        self.assertEqual(totals.total, 3)

    def test_csv_agrees_with_list_and_alias(self):
        self._own("sms", _at(DAY2, 9))
        text = export_campaign_send_totals_summary_csv(self.salon, DAY1, DAY3)
        parsed = [
            {**r, "salon_id": int(r["salon_id"]), "count": int(r["count"])}
            for r in _rows(text)
        ]
        self.assertEqual(
            parsed, export_campaign_send_totals_summary(self.salon, DAY1, DAY3))
        self.assertEqual(
            campaign_send_totals_export_csv(self.salon, DAY1, DAY3), text)


class EmptyPeriodTests(CampaignSendTotalsExportBase):
    def test_empty_period_zero_rows_not_none(self):
        rows = export_campaign_send_totals_summary(self.salon, DAY1, DAY3)
        self.assertEqual(
            rows,
            [{"salon_id": self.salon.pk,
              "start_date": DAY1.isoformat(), "end_date": DAY3.isoformat(),
              "channel": channel, "status": "sent", "count": 0}
             for channel in ("sms", "email")])
        self.assertEqual(sum(r["count"] for r in rows), 0)
        parsed = _rows(
            export_campaign_send_totals_summary_csv(self.salon, DAY1, DAY3))
        self.assertEqual([int(r["count"]) for r in parsed], [0, 0])

    def test_no_export_ranges_are_header_only(self):
        header = ",".join(CAMPAIGN_TOTALS_EXPORT_FIELDNAMES) + "\n"
        self.assertEqual(
            export_campaign_send_totals_summary(self.salon, DAY3, DAY1), [])
        self.assertEqual(export_campaign_send_totals_summary(None, DAY1), [])
        self.assertEqual(
            export_campaign_send_totals_summary_csv(self.salon, DAY3, DAY1),
            header)

    def test_read_only_no_mutation(self):
        row = self._own("email", _at(DAY1, 9))
        before = CampaignSend.objects.count()
        export_campaign_send_totals_summary_csv(self.salon, DAY1, DAY3)
        self.assertEqual(CampaignSend.objects.count(), before)
        row.refresh_from_db()
        self.assertEqual(row.channel, "email")
