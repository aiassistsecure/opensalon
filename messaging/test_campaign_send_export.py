import csv
import io
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import TestCase
from clients.models import Client
from messaging.campaign_send_export import (
    DETAIL_EXPORT_FIELDNAMES,
    EXPORT_FIELDNAMES,
    campaign_send_export_csv,
    export_campaign_send_totals_detail,
    export_campaign_send_totals_detail_csv,
)
from messaging.campaign_send_totals import campaign_send_totals
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


class CampaignSendExportBase(TestCase):
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


class HeaderTests(CampaignSendExportBase):
    def test_csv_header_and_row_keys(self):
        self.assertEqual(DETAIL_EXPORT_FIELDNAMES, EXPORT_FIELDNAMES)
        self.assertEqual(EXPORT_FIELDNAMES,
                         ["salon_id", "date", "channel", "count"])
        text = export_campaign_send_totals_detail_csv(self.salon, DAY1, DAY3)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        rows = export_campaign_send_totals_detail(self.salon, DAY1, DAY3)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(list(row), EXPORT_FIELDNAMES)
        self.assertEqual(list(_rows(text)[0]), EXPORT_FIELDNAMES)


class DetailMatchServiceTests(CampaignSendExportBase):
    def test_rows_verbatim_from_campaign_send_totals(self):
        self._own("email", _at(DAY1, 9))
        self._own("email", _at(DAY1, 10))
        self._own("sms", _at(DAY2, 9))
        self._send(self.other, "email", _at(DAY1, 9))
        totals = campaign_send_totals(self.salon, DAY1, DAY3)
        rows = export_campaign_send_totals_detail(self.salon, DAY1, DAY3)
        expected = [
            {"salon_id": self.salon.pk, "date": day.isoformat(),
             "channel": channel,
             "count": totals.by_day_by_channel[day][channel]}
            for day in (DAY1, DAY2, DAY3)
            for channel in ("sms", "email")
        ]
        self.assertEqual(rows, expected)
        self.assertEqual(sum(r["count"] for r in rows), totals.total)
        self.assertEqual(totals.total, 3)

    def test_per_day_rows(self):
        self._own("sms", _at(DAY1, 9))
        self._own("sms", _at(DAY3, 9))
        rows = export_campaign_send_totals_detail(self.salon, DAY1, DAY3)
        by_key = {(r["date"], r["channel"]): r["count"] for r in rows}
        self.assertEqual(by_key[(DAY1.isoformat(), "sms")], 1)
        self.assertEqual(by_key[(DAY2.isoformat(), "sms")], 0)
        self.assertEqual(by_key[(DAY3.isoformat(), "sms")], 1)
        self.assertEqual(len(rows), 6)

    def test_csv_agrees_with_list_single_day_and_alias(self):
        self._own("sms", _at(DAY2, 9))
        text = export_campaign_send_totals_detail_csv(self.salon, DAY2)
        parsed = [
            {**r, "salon_id": int(r["salon_id"]), "count": int(r["count"])}
            for r in _rows(text)
        ]
        self.assertEqual(
            parsed, export_campaign_send_totals_detail(self.salon, DAY2))
        self.assertEqual(campaign_send_export_csv(self.salon, DAY2), text)


class EmptyAndScopeTests(CampaignSendExportBase):
    def test_empty_period_zero_rows_not_none(self):
        rows = export_campaign_send_totals_detail(self.salon, DAY1, DAY3)
        self.assertEqual(
            rows,
            [{"salon_id": self.salon.pk, "date": d.isoformat(),
              "channel": c, "count": 0}
             for d in (DAY1, DAY2, DAY3) for c in ("sms", "email")])
        parsed = _rows(
            export_campaign_send_totals_detail_csv(self.salon, DAY1, DAY3))
        self.assertEqual([int(r["count"]) for r in parsed], [0] * 6)

    def test_no_export_ranges_are_header_only(self):
        header = ",".join(EXPORT_FIELDNAMES) + "\n"
        self.assertEqual(
            export_campaign_send_totals_detail(self.salon, DAY3, DAY1), [])
        self.assertEqual(export_campaign_send_totals_detail(None, DAY1), [])
        self.assertEqual(export_campaign_send_totals_detail(self.salon, None),
                         [])
        self.assertEqual(
            export_campaign_send_totals_detail_csv(self.salon, DAY3, DAY1),
            header)

    def test_other_salon_excluded(self):
        self._own("email", _at(DAY1, 9))
        self._send(self.other, "email", _at(DAY1, 9))
        rows = export_campaign_send_totals_detail(self.salon, DAY1, DAY1)
        self.assertEqual(sum(r["count"] for r in rows), 1)

    def test_read_only_no_mutation(self):
        row = self._own("email", _at(DAY1, 9))
        before = CampaignSend.objects.count()
        export_campaign_send_totals_detail_csv(self.salon, DAY1, DAY3)
        export_campaign_send_totals_detail(self.salon, DAY1, DAY3)
        self.assertEqual(CampaignSend.objects.count(), before)
        row.refresh_from_db()
        self.assertEqual(row.channel, "email")
