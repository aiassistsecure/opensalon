"""Tests for prior cashup history, CSV export, and command.
Synthetic fixtures; current 2026-10-08..14, prior 10-01..07."""
import csv
import datetime
import io
import json
import os
import shutil
import tempfile
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.cashup_history import cashup_history
from checkout.models import Cashup
from checkout.prior_cashup_history import prior_cashup_history
from checkout.prior_cashup_history_export import (
    EXPORT_FIELDNAMES, export_prior_cashup_history,
    export_prior_cashup_history_csv)
from saloncore.models import Salon

D = datetime.date
TD = datetime.timedelta
START, END = D(2026, 10, 8), D(2026, 10, 14)
P_START, P_END = D(2026, 10, 1), D(2026, 10, 7)


def _stamp(day, hour=9):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)),
        datetime.timezone.utc)


class PriorCashupHistoryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self._cashup(self.salon, P_START + TD(days=1),
                     {"cash": "50.00", "external": "25.00"}, "75.00")
        self._cashup(self.salon, P_START + TD(days=2), {"voucher": "25.00"}, "25.00")
        self._cashup(self.salon, START,
                     {"cash": "100.00", "external": "50.00"}, "150.00")
        self._cashup(self.salon, START + TD(days=2), {"cash": "50.00"}, "50.00")
        self._cashup(self.other, START, {"cash": "999.00"}, "999.00")
        self._cashup(self.salon, D(2026, 9, 30), {"cash": "999.00"}, "999.00")

    def _cashup(self, salon, day, totals, total, hour=9):
        return Cashup.objects.create(
            salon=salon, period_start=_stamp(day, hour),
            period_end=_stamp(day, hour + 1),
            tender_totals=dict(totals), total=Decimal(total))

    def test_both_windows_verbatim(self):
        r = prior_cashup_history(self.salon, START, END)
        cur, pri = cashup_history(self.salon, START, END), cashup_history(self.salon, P_START, P_END)
        self.assertEqual((r.prior_start, r.prior_end), (P_START, P_END))
        self.assertEqual((r.current, r.prior), (cur, pri))
        self.assertEqual((r.current_summary, r.prior_summary), (cur.summary, pri.summary))
        self.assertEqual(r.salon_id, self.salon.pk); self.assertFalse(r.is_locked)

    def test_delta_and_percent_change(self):
        r = prior_cashup_history(self.salon, START, END)
        self.assertEqual((r.cashup_count.current, r.cashup_count.prior,
                          r.cashup_count.delta, r.cashup_count.percent_change),
                         (2, 2, 0, Decimal("0.00")))
        self.assertEqual((r.total_taken.current, r.total_taken.prior,
                          r.total_taken.delta, r.total_taken.percent_change),
                         (Decimal("200.00"), Decimal("100.00"),
                          Decimal("100.00"), Decimal("100.00")))

    def test_by_tender_union_zeros_on_missing_side(self):
        r = prior_cashup_history(self.salon, START, END)
        self.assertEqual([e.method for e in r.entries], ["cash", "external", "voucher"])
        cash, ext, voucher = r.entries
        self.assertEqual((cash.current, cash.prior, cash.delta, cash.percent_change),
                         (Decimal("150.00"), Decimal("50.00"), Decimal("100.00"), Decimal("200.00")))
        self.assertEqual((ext.current, ext.prior, ext.delta, ext.percent_change),
                         (Decimal("50.00"), Decimal("25.00"), Decimal("25.00"), Decimal("100.00")))
        self.assertEqual((voucher.current, voucher.prior, voucher.delta, voucher.percent_change),
                         (Decimal("0.00"), Decimal("25.00"), Decimal("-25.00"), Decimal("-100.00")))
        self.assertEqual(r["cash"].current, Decimal("150.00"))
        self.assertEqual(r.by_tender["voucher"].prior, Decimal("25.00"))  # noqa

    def test_expected_and_variance_stay_none(self):
        r = prior_cashup_history(self.salon, START, END)
        for fig in (r.expected_total, r.variance):
            self.assertIsNone(fig.current); self.assertIsNone(fig.prior)
            self.assertIsNone(fig.delta); self.assertIsNone(fig.percent_change)

    def test_none_percent_when_prior_zero(self):
        self._cashup(self.salon, D(2026, 8, 10), {"cash": "40.00"}, "40.00")
        r = prior_cashup_history(self.salon, D(2026, 8, 8), D(2026, 8, 14))
        self.assertEqual(r.prior_summary.cashup_count, 0)
        self.assertEqual((r.total_taken.current, r.total_taken.prior),
                         (Decimal("40.00"), Decimal("0.00")))
        self.assertIsNone(r.total_taken.percent_change)
        self.assertIsNone(r.cashup_count.percent_change)
        self.assertIsNone(r["cash"].percent_change)
        empty = prior_cashup_history(self.salon, D(2026, 6, 1), D(2026, 6, 7))
        self.assertEqual((empty.total_taken.current, empty.total_taken.prior),
                         (Decimal("0.00"), Decimal("0.00")))
        self.assertIsNone(empty.total_taken.percent_change)

    def test_datetime_window_shifts_by_duration(self):
        self._cashup(self.salon, P_END, {"cash": "30.00"}, "30.00", hour=12)
        r = prior_cashup_history(self.salon, _stamp(START, 0), _stamp(START, 23))
        self.assertEqual((r.prior_start, r.prior_end), (_stamp(P_END, 1), _stamp(START, 0)))
        self.assertEqual((r.cashup_count.current, r.cashup_count.prior), (1, 1))
        self.assertEqual((r.total_taken.current, r.total_taken.prior),
                         (Decimal("150.00"), Decimal("30.00")))

    def test_reversed_and_missing_raise(self):
        for args in [(self.salon, END, START), (None, START, END),
                     (self.salon, START, None), (self.salon,)]:
            with self.assertRaises(ValueError):
                prior_cashup_history(*args)

    def test_csv_rows_match_service(self):
        rows = export_prior_cashup_history(self.salon, START, END)
        self.assertEqual([list(r) for r in rows], [EXPORT_FIELDNAMES] * len(rows))
        self.assertEqual([r["figure"] for r in rows],
                         ["cashup_count", "total_taken", "expected_total",
                          "variance", "by_tender", "by_tender", "by_tender"])
        count, total, expected, variance = rows[:4]
        self.assertEqual((count["current"], count["prior"], count["delta"],
                          count["percent_change"]), ("2", "2", "0", "0.00"))
        self.assertEqual((total["current"], total["prior"], total["delta"],
                          total["percent_change"]),
                         ("200.00", "100.00", "100.00", "100.00"))
        self.assertEqual((expected["current"], expected["prior"],
                          expected["delta"], expected["percent_change"]), ("", "", "", ""))
        self.assertEqual(variance["current"], "")
        voucher = rows[-1]
        self.assertEqual((voucher["tender"], voucher["current"], voucher["prior"],
                          voucher["delta"], voucher["percent_change"]),
                         ("voucher", "0.00", "25.00", "-25.00", "-100.00"))
        self.assertEqual((count["start"], count["prior_start"], count["prior_end"]),
                         (START.isoformat(), P_START.isoformat(), P_END.isoformat()))
        text = export_prior_cashup_history_csv(self.salon, START, END)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual([{**r, "salon_id": int(r["salon_id"])} for r in parsed], rows)

    def test_command_stdout_and_file_match_service(self):
        out = io.StringIO()
        call_command("export_prior_cashup_history", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        expected = export_prior_cashup_history_csv(self.salon, START, END)
        self.assertEqual(out.getvalue(), expected)
        tmp = os.path.join(os.getcwd(), "tmp_prior_cashup_test")
        os.makedirs(tmp, exist_ok=True)
        try:
            path = os.path.join(tmp, "prior.csv")
            call_command("export_prior_cashup_history", salon_id=self.salon.pk,
                         start_date=START.isoformat(), end_date=END.isoformat(),
                         output=path, stdout=io.StringIO())
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), expected)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_command_errors(self):
        bad = os.path.join(os.getcwd(), "no_such_dir_prior_cashup", "x.csv")
        cases = [
            dict(salon_id=self.salon.pk + 999, start_date=START, end_date=END),
            dict(salon_id=self.salon.pk, start_date="not-a-date", end_date=END),
            dict(salon_id=self.salon.pk),
            dict(salon_id=self.salon.pk, start_date=END, end_date=START),
            dict(salon_id=self.salon.pk, start_date=START, end_date=END, output=bad),
        ]
        for kwargs in cases:
            with self.assertRaises(CommandError):
                call_command("export_prior_cashup_history", stdout=io.StringIO(), **kwargs)

    def test_command_default_is_csv_byte_identical(self):
        default_out, csv_out = io.StringIO(), io.StringIO()
        call_command("export_prior_cashup_history", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=default_out)
        call_command("export_prior_cashup_history", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="csv",
                     stdout=csv_out)
        self.assertEqual(default_out.getvalue(), csv_out.getvalue())
        self.assertEqual(default_out.getvalue(),
                         export_prior_cashup_history_csv(self.salon, START, END))

    def test_command_explicit_csv_via_cli_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_cashup_history", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_cashup_history_csv(self.salon, START, END))

    def test_command_json_parses_and_equals_dict_service(self):
        out = io.StringIO()
        call_command("export_prior_cashup_history", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_prior_cashup_history(self.salon, START, END))
        self.assertIn("200.00", out.getvalue())

    def test_command_json_via_cli_matches_dict_service(self):
        out = io.StringIO()
        call_command("export_prior_cashup_history", "--salon-id",
                     str(self.salon.pk), "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_prior_cashup_history(self.salon, START, END))

    def test_command_json_delegates_to_dict_service_verbatim(self):
        with mock.patch(
            "checkout.management.commands.export_prior_cashup_history"
            ".export_prior_cashup_history",
            wraps=export_prior_cashup_history,
        ) as spy:
            call_command("export_prior_cashup_history",
                         salon_id=self.salon.pk, start_date=START,
                         end_date=END, format="json", stdout=io.StringIO())
        spy.assert_called_once_with(self.salon, START, END)

    def test_command_json_output_file_matches_dict_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_cashup_history.json")
            call_command("export_prior_cashup_history",
                         salon_id=self.salon.pk, start_date=START,
                         end_date=END, format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(json.loads(written),
                         export_prior_cashup_history(self.salon, START, END))
        self.assertEqual(out.getvalue(), "")

    def test_command_json_service_error_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_cashup_history",
                         salon_id=self.salon.pk, start_date=END,
                         end_date=START, format="json", stdout=io.StringIO())

    def test_command_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_cashup_history",
                         salon_id=self.salon.pk, start_date=START,
                         end_date=END, format="xml", stdout=io.StringIO())

    def test_command_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_cashup_history", "--salon-id",
                         str(self.salon.pk), "--start-date", START.isoformat(),
                         "--end-date", END.isoformat(), "--format", "xml",
                         stdout=io.StringIO())
