import csv, datetime, io, json  # noqa: E401
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
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

    def test_by_channel_by_status_verbatim_and_deltas(self):
        self._book()
        r = prior_campaign_send_totals(self.salon, C1, C2)
        cross = r.by_channel_by_status
        self.assertEqual((cross["email"]["sent"].current,
                          cross["email"]["sent"].prior,
                          cross["email"]["sent"].delta,
                          cross["email"]["sent"].percent_change),
                         (2, 1, 1, Decimal("100.00")))
        self.assertEqual((cross["sms"]["sent"].current,
                          cross["sms"]["sent"].prior,
                          cross["sms"]["sent"].percent_change),
                         (3, 1, Decimal("200.00")))
        # Verbatim from the source's own cross-tab, both windows.
        cur = campaign_send_totals(self.salon, C1, C2)
        pri = campaign_send_totals(self.salon, P1, P2)
        for ch, cells in cross.items():
            for status, delta in cells.items():
                self.assertEqual(
                    delta.current,
                    cur.by_channel_by_status[ch][status])
                self.assertEqual(
                    delta.prior, pri.by_channel_by_status[ch][status])
        # Cross cells sum to by_channel and by_status deltas.
        for ch, delta in r.by_channel.items():
            self.assertEqual(
                sum(c.current for c in cross[ch].values()),
                delta.current)
        self.assertEqual(
            r.as_dict()["by_channel_by_status"]["sms"]["sent"]["prior"], 1)
        self.assertEqual(r.deltas["by_channel_by_status"], cross)

    def test_by_day_by_channel_offset_aligned_verbatim(self):
        self._book()
        r = prior_campaign_send_totals(self.salon, C1, C2)
        cells = r.by_day_by_channel
        self.assertEqual(list(cells), [C1, C2])
        # C1 pairs with P1, C2 with P2 (offset alignment, as by_day).
        self.assertEqual((cells[C1]["email"].current,
                          cells[C1]["email"].prior,
                          cells[C1]["email"].delta,
                          cells[C1]["email"].percent_change),
                         (2, 1, 1, Decimal("100.00")))
        self.assertEqual((cells[C1]["sms"].current,
                          cells[C1]["sms"].prior), (1, 0))
        self.assertIsNone(cells[C1]["sms"].percent_change)
        self.assertEqual((cells[C2]["sms"].current,
                          cells[C2]["sms"].prior), (2, 1))
        self.assertEqual((cells[C2]["email"].current,
                          cells[C2]["email"].prior), (0, 0))
        self.assertIsNone(cells[C2]["email"].percent_change)
        # Verbatim from the source's own by_day_by_channel,
        # prior side read at the offset-paired prior day.
        cur = campaign_send_totals(self.salon, C1, C2)
        pri = campaign_send_totals(self.salon, P1, P2)
        for offset, day in enumerate([C1, C2]):
            prior_day = [P1, P2][offset]
            for ch, delta in cells[day].items():
                self.assertEqual(
                    delta.current, cur.by_day_by_channel[day][ch])
                self.assertEqual(
                    delta.prior, pri.by_day_by_channel[prior_day][ch])
        # Cells sum to the by_day delta for every day.
        for day, delta in r.by_day.items():
            self.assertEqual(
                sum(c.current for c in cells[day].values()),
                delta.current)
            self.assertEqual(
                sum(c.prior for c in cells[day].values()), delta.prior)
        self.assertEqual(
            r.as_dict()["by_day_by_channel"][C1.isoformat()]
            ["email"]["current"], 2)

    def test_new_breakdowns_prior_zero_percent_none(self):
        r = prior_campaign_send_totals(self.salon, C1, C2)
        self.assertIsNone(
            r.by_channel_by_status["email"]["sent"].percent_change)
        self.assertIsNone(
            r.by_day_by_channel[C1]["email"].percent_change)
        self._book()
        # Current window is the prior book; its prior is empty,
        # so every new-breakdown cell has prior 0 -> None.
        r2 = prior_campaign_send_totals(self.salon, P1, P2)
        self.assertEqual(
            r2.by_channel_by_status["email"]["sent"].current, 1)
        self.assertEqual(
            r2.by_channel_by_status["email"]["sent"].prior, 0)
        self.assertIsNone(
            r2.by_channel_by_status["email"]["sent"].percent_change)
        self.assertEqual(r2.by_day_by_channel[P2]["sms"].current, 1)
        self.assertIsNone(
            r2.by_day_by_channel[P2]["sms"].percent_change)

    def test_export_includes_new_breakdown_rows(self):
        self._book()
        rows = export_prior_campaign_send_totals(self.salon, C1, C2)
        by_metric = {row["metric"]: row for row in rows}
        self.assertEqual(
            (by_metric["channel_email_status_sent"]["current"],
             by_metric["channel_email_status_sent"]["prior"],
             by_metric["channel_email_status_sent"]["percent_change"]),
            (2, 1, Decimal("100.00")))
        self.assertEqual(
            by_metric["channel_sms_status_sent"]["current"], 3)
        self.assertEqual(
            (by_metric[f"day_{C1.isoformat()}_email"]["current"],
             by_metric[f"day_{C1.isoformat()}_email"]["prior"]), (2, 1))
        self.assertIsNone(
            by_metric[f"day_{C1.isoformat()}_sms"]["percent_change"])
        self.assertEqual(
            by_metric[f"day_{C2.isoformat()}_sms"]["current"], 2)
        text = export_prior_campaign_send_totals_csv(self.salon, C1, C2)
        csv_rows = {row["metric"]: row
                    for row in csv.DictReader(io.StringIO(text))}
        self.assertEqual(len(csv_rows), len(rows))
        self.assertEqual(
            csv_rows["channel_sms_status_sent"]["percent_change"],
            "200.00")
        self.assertEqual(
            csv_rows[f"day_{C1.isoformat()}_sms"]["percent_change"], "")
        self.assertEqual(
            csv_rows[f"day_{C2.isoformat()}_sms"]["current"], "2")

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_campaign_send_totals",
                     salon_id=self.salon.pk, start_date=C1, end_date=C2,
                     stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_campaign_send_totals_csv(self.salon, C1, C2))
        self.assertIn("channel_sms_status_sent", out.getvalue())
        self.assertIn(f"day_{C1.isoformat()}_email", out.getvalue())
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

    def _json_expected(self, salon, start, end):
        rows = export_prior_campaign_send_totals(salon, start, end)
        return [{**row, "percent_change": (
            None if row["percent_change"] is None
            else str(row["percent_change"]))} for row in rows]

    def test_command_default_and_explicit_csv_byte_identical(self):
        self._book()
        expected = export_prior_campaign_send_totals_csv(
            self.salon, C1, C2)
        for kwargs in ({}, {"format": "csv"}):
            out = io.StringIO()
            call_command("export_prior_campaign_send_totals",
                         salon_id=self.salon.pk, start_date=C1,
                         end_date=C2, stdout=out, **kwargs)
            self.assertEqual(out.getvalue(), expected)

    def test_command_json_parses_and_equals_dict_rows(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_campaign_send_totals",
                     salon_id=self.salon.pk, start_date=C1, end_date=C2,
                     format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         self._json_expected(self.salon, C1, C2))
        self.assertEqual(
            out.getvalue(),
            json.dumps(export_prior_campaign_send_totals(
                self.salon, C1, C2), indent=2,
                cls=DjangoJSONEncoder) + "\n")

    def test_command_json_via_cli_flags(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_campaign_send_totals",
                     "--salon-id", str(self.salon.pk),
                     "--start-date", C1.isoformat(),
                     "--end-date", C2.isoformat(),
                     "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         self._json_expected(self.salon, C1, C2))

    def test_command_json_output_file(self):
        self._book()
        m = mock.mock_open()
        with mock.patch(
                "messaging.management.commands."
                "export_prior_campaign_send_totals.open", m):
            call_command("export_prior_campaign_send_totals",
                         salon_id=self.salon.pk,
                         start_date="2026-03-03", end_date="2026-03-04",
                         format="json", output="out.json")
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertEqual(json.loads(written),
                         self._json_expected(self.salon, C1, C2))

    def test_command_invalid_format_raises(self):
        self._book()
        with self.assertRaises(CommandError):
            call_command("export_prior_campaign_send_totals",
                         salon_id=self.salon.pk, start_date=C1,
                         end_date=C2, format="xml", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_campaign_send_totals",
                         "--salon-id", str(self.salon.pk),
                         "--start-date", C1.isoformat(),
                         "--end-date", C2.isoformat(),
                         "--format", "xml", stdout=io.StringIO())

    def test_command_json_service_error_raises(self):
        with mock.patch(
                "messaging.management.commands."
                "export_prior_campaign_send_totals."
                "export_prior_campaign_send_totals",
                side_effect=ValueError("boom")):
            with self.assertRaises(CommandError):
                call_command("export_prior_campaign_send_totals",
                             salon_id=self.salon.pk, start_date=C1,
                             end_date=C2, format="json",
                             stdout=io.StringIO())
