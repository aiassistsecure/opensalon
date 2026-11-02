"""Tests for campaign_send_detail service + export command."""
import csv
import io
from datetime import date, datetime, time
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase

from clients.models import Client
from messaging.campaign_send_detail import (
    CAMPAIGN_SEND_DETAIL_FIELDNAMES,
    campaign_send_detail_row,
    export_campaign_send_detail,
    export_campaign_send_detail_csv,
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


def _cmd():
    return load_command_class("messaging", "export_campaign_send_detail")


class CampaignSendDetailBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self._n = 0

    def _send(self, salon, channel, when, status="sent", detail=""):
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
            status=status, sent_at=when, detail=detail)

    def _own(self, channel, when, **kw):
        return self._send(self.salon, channel, when, **kw)


class DetailServiceTests(CampaignSendDetailBase):
    def test_header_and_row_keys(self):
        self.assertEqual(CAMPAIGN_SEND_DETAIL_FIELDNAMES, [
            "id", "salon_id", "campaign_id", "client_id",
            "channel", "status", "sent_at", "detail"])
        text = export_campaign_send_detail_csv(self.salon, DAY1, DAY3)
        self.assertEqual(text.splitlines()[0],
                         ",".join(CAMPAIGN_SEND_DETAIL_FIELDNAMES))

    def test_one_row_per_send_oldest_first(self):
        second = self._own("email", _at(DAY1, 10))
        first = self._own("sms", _at(DAY1, 9))
        rows = export_campaign_send_detail(self.salon, DAY1, DAY3)
        self.assertEqual([r["id"] for r in rows], [first.pk, second.pk])
        self.assertEqual(rows[0], campaign_send_detail_row(first))
        self.assertEqual(rows[0]["campaign_id"], first.campaign_id)
        self.assertEqual(rows[0]["client_id"], first.client_id)
        self.assertEqual(rows[0]["salon_id"], self.salon.pk)
        self.assertEqual(rows[0]["channel"], "sms")
        self.assertEqual(rows[0]["status"], "sent")
        self.assertEqual(rows[0]["sent_at"], _at(DAY1, 9).isoformat())
        for row in rows:
            self.assertEqual(list(row), CAMPAIGN_SEND_DETAIL_FIELDNAMES)

    def test_row_count_matches_totals_and_csv_agrees(self):
        self._own("email", _at(DAY1, 9))
        self._own("sms", _at(DAY2, 9))
        self._send(self.other, "email", _at(DAY1, 9))
        rows = export_campaign_send_detail(self.salon, DAY1, DAY3)
        totals = campaign_send_totals(self.salon, DAY1, DAY3)
        self.assertEqual(len(rows), totals.total)
        self.assertEqual(totals.total, 2)
        parsed = _rows(export_campaign_send_detail_csv(self.salon, DAY1, DAY3))
        self.assertEqual([int(r["id"]) for r in parsed],
                         [r["id"] for r in rows])
        self.assertEqual([r["sent_at"] for r in parsed],
                         [r["sent_at"] for r in rows])

    def test_no_client_contact_details_exported(self):
        self._own("email", _at(DAY1, 9))
        text = export_campaign_send_detail_csv(self.salon, DAY1, DAY3)
        self.assertNotIn("@example.com", text)
        self.assertNotIn("555-0100", text)

    def test_single_day_default_and_boundaries(self):
        self._own("email", _at(DAY1, 9))
        self._own("email", _at(DAY2, 9))
        self._own("email", _at(DAY3, 9))
        rows = export_campaign_send_detail(self.salon, DAY2)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["sent_at"].startswith(DAY2.isoformat()))

    def test_no_export_ranges(self):
        header = ",".join(CAMPAIGN_SEND_DETAIL_FIELDNAMES) + "\n"
        self.assertEqual(export_campaign_send_detail(self.salon, DAY3, DAY1),
                         [])
        self.assertEqual(export_campaign_send_detail(None, DAY1), [])
        self.assertEqual(export_campaign_send_detail(self.salon, None), [])
        self.assertEqual(
            export_campaign_send_detail_csv(self.salon, DAY3, DAY1), header)
        self.assertEqual(export_campaign_send_detail(self.salon, DAY1, DAY3),
                         [])

    def test_other_salon_excluded_and_read_only(self):
        row = self._own("email", _at(DAY1, 9))
        self._send(self.other, "email", _at(DAY1, 9))
        before = CampaignSend.objects.count()
        rows = export_campaign_send_detail(self.salon, DAY1, DAY3)
        export_campaign_send_detail_csv(self.salon, DAY1, DAY3)
        self.assertEqual([r["id"] for r in rows], [row.pk])
        self.assertEqual(CampaignSend.objects.count(), before)
        row.refresh_from_db()
        self.assertEqual(row.channel, "email")


class DetailCommandTests(CampaignSendDetailBase):
    def setUp(self):
        super().setUp()
        self._own("email", _at(DAY1, 9))
        self._own("sms", _at(DAY2, 9))
        self._send(self.other, "email", _at(DAY1, 9))

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk,
                     date_from=DAY1, date_to=DAY3, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_campaign_send_detail_csv(self.salon, DAY1, DAY3))

    def test_stdout_matches_service_with_cli_args(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--date-from", DAY1.isoformat(),
                     "--date-to", DAY3.isoformat(), stdout=out)
        self.assertEqual(out.getvalue(),
                         export_campaign_send_detail_csv(self.salon, DAY1, DAY3))

    def test_output_file_matches_service(self):
        # ``open`` is mocked: some sandboxes forbid real file
        # writes from test processes, and the command's contract
        # is the exact text it hands to the file, not the FS.
        out = io.StringIO()
        opener = mock.mock_open()
        with mock.patch("builtins.open", opener):
            call_command(_cmd(), salon_id=self.salon.pk,
                         date_from=DAY1, date_to=DAY3,
                         output="detail.csv", stdout=out)
        written = "".join(
            call.args[0] for call in opener().write.call_args_list)
        self.assertEqual(written,
                         export_campaign_send_detail_csv(self.salon, DAY1, DAY3))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_and_unwritable_output(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=self.salon.pk + 1000,
                         date_from=DAY1, stdout=io.StringIO())
        with mock.patch("builtins.open", side_effect=OSError("nope")):
            with self.assertRaises(CommandError):
                call_command(_cmd(), salon_id=self.salon.pk,
                             date_from=DAY1, output="detail.csv",
                             stdout=io.StringIO())
