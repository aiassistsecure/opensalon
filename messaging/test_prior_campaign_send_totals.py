import csv, datetime, io  # noqa: E401
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from clients.models import Client
from messaging.campaign_send_totals import campaign_send_totals
from messaging.models import Campaign, CampaignSend
from messaging.prior_campaign_send_totals import prior_campaign_send_totals
from messaging.prior_campaign_send_totals_export import (
    PRIOR_CAMPAIGN_SEND_TOTALS_FIELDNAMES,
    export_prior_campaign_send_totals,
    export_prior_campaign_send_totals_csv,
)
from saloncore.models import Salon

UTC = datetime.timezone.utc
P1 = datetime.date(2026, 3, 1)
P2 = datetime.date(2026, 3, 2)
C1 = datetime.date(2026, 3, 3)
C2 = datetime.date(2026, 3, 4)


def at(day, hour=12):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class PriorCampaignSendTotalsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self._n = 0

    def _send(self, salon, channel, when):
        self._n += 1
        client = Client.objects.create(
            salon=salon, first_name=f"C{self._n}", last_name="Example",
            email=f"c{self._n}@example.com", sms_opt_in=True,
            email_opt_in=True)
        campaign = Campaign.objects.create(
            salon=salon, name=f"Campaign {self._n}", channel=channel,
            body="Hello", status=Campaign.Status.SENT, sent_at=when)
        return CampaignSend.objects.create(
            campaign=campaign, client=client, channel=channel,
            status="sent", sent_at=when)

    def _book(self):
        # Prior (P1-P2): email 1 (P1), sms 1 (P2) -> total 2.
        self._send(self.salon, "email", at(P1, 9))
        self._send(self.salon, "sms", at(P2, 9))
        # Current (C1-C2): email 2, sms 3 -> total 5.
        self._send(self.salon, "email", at(C1, 9))
        self._send(self.salon, "email", at(C1, 10))
        self._send(self.salon, "sms", at(C1, 11))
        self._send(self.salon, "sms", at(C2, 9))
        self._send(self.salon, "sms", at(C2, 10))
        # Other salon in current window: never counted.
        self._send(self.other, "email", at(C1, 9))

    def test_both_windows_verbatim_and_deltas(self):
        self._book()
        r = prior_campaign_send_totals(self.salon, C1, C2)
        self.assertEqual((r.start_date, r.end_date), (C1, C2))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (P1, P2))
        self.assertEqual(r.days, 2)
        self.assertEqual(r.current, campaign_send_totals(self.salon, C1, C2))
        self.assertEqual(r.prior, campaign_send_totals(self.salon, P1, P2))
        self.assertEqual(r.current_campaign, r.current)
        self.assertEqual((r.total.current, r.total.prior, r.total.delta,
                          r.total.percent_change),
                         (5, 2, 3, Decimal("150.00")))
        self.assertEqual((r.by_channel["email"].current,
                          r.by_channel["email"].prior,
                          r.by_channel["email"].delta,
                          r.by_channel["email"].percent_change),
                         (2, 1, 1, Decimal("100.00")))
        self.assertEqual((r.by_channel["sms"].current,
                          r.by_channel["sms"].prior,
                          r.by_channel["sms"].percent_change),
                         (3, 1, Decimal("200.00")))
        self.assertEqual((r.by_status["sent"].current,
                          r.by_status["sent"].prior), (5, 2))
        self.assertEqual((r.by_day[C1].current, r.by_day[C1].prior,
                          r.by_day[C1].delta), (3, 1, 2))
        self.assertEqual((r.by_day[C2].current, r.by_day[C2].prior), (2, 1))
        self.assertEqual(r.as_dict()["total"]["delta"], 3)
        self.assertEqual(r.as_dict()["by_channel"]["sms"]["current"], 3)

    def test_zero_prior_percent_none_and_empty(self):
        r = prior_campaign_send_totals(self.salon, C1, C2)
        self.assertEqual((r.total.current, r.total.prior), (0, 0))
        self.assertIsNone(r.total.percent_change)
        self._book()
        r2 = prior_campaign_send_totals(self.salon, P1, P2)
        self.assertEqual(r2.total.prior, 0)
        self.assertIsNone(r2.total.percent_change)
        self.assertIsNone(r2.by_channel["sms"].percent_change
                          if r2.by_channel["sms"].prior == 0 else None)

    def test_aliases_single_day_and_reversed(self):
        self._book()
        r = prior_campaign_send_totals(
            self.salon, date_from=C1, date_to=C2)
        self.assertEqual(r.total.current, 5)
        single = prior_campaign_send_totals(self.salon, C1)
        self.assertEqual((single.prior_start_date, single.prior_end_date),
                         (P2, P2))
        self.assertEqual(single.total.current, 3)
        with self.assertRaises(ValueError):
            prior_campaign_send_totals(self.salon, C2, C1)
        with self.assertRaises(ValueError):
            prior_campaign_send_totals(None, C1, C2)
        with self.assertRaises(ValueError):
            export_prior_campaign_send_totals_csv(self.salon, C2, C1)

    def test_export_dict_and_csv_agree(self):
        self._book()
        rows = export_prior_campaign_send_totals(self.salon, C1, C2)
        by_metric = {row["metric"]: row for row in rows}
        self.assertEqual((by_metric["total"]["current"],
                          by_metric["total"]["prior"],
                          by_metric["total"]["delta"],
                          by_metric["total"]["percent_change"]),
                         (5, 2, 3, Decimal("150.00")))
        self.assertEqual(by_metric["channel_sms"]["current"], 3)
        self.assertEqual(by_metric["status_sent"]["current"], 5)
        self.assertIn(f"day_{C1.isoformat()}", by_metric)
        text = export_prior_campaign_send_totals_csv(self.salon, C1, C2)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         PRIOR_CAMPAIGN_SEND_TOTALS_FIELDNAMES)
        csv_rows = {row["metric"]: row
                    for row in csv.DictReader(io.StringIO(text))}
        self.assertEqual((csv_rows["total"]["current"],
                          csv_rows["total"]["prior"],
                          csv_rows["total"]["delta"],
                          csv_rows["total"]["percent_change"]),
                         ("5", "2", "3", "150.00"))
        self.assertEqual(csv_rows["total"]["prior_start_date"],
                         P1.isoformat())
        self.assertEqual(len(csv_rows), len(rows))

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_campaign_send_totals",
                     salon_id=self.salon.pk, start_date=C1, end_date=C2,
                     stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_campaign_send_totals_csv(self.salon, C1, C2))
        for kwargs in (dict(salon_id=self.salon.pk + 1000,
                            start_date=C1, end_date=C2),
                       dict(salon_id=self.salon.pk,
                            start_date=C2, end_date=C1),
                       dict(salon_id=self.salon.pk,
                            start_date="not-a-date", end_date=C2),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_campaign_send_totals",
                             stdout=io.StringIO(), **kwargs)
        m = mock.mock_open()
        with mock.patch(
                "messaging.management.commands."
                "export_prior_campaign_send_totals.open", m):
            call_command("export_prior_campaign_send_totals",
                         salon_id=self.salon.pk,
                         start_date="2026-03-03", end_date="2026-03-04",
                         output="out.csv")
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertIn("150.00", written)
