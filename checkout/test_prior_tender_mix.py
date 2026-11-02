"""Tests for prior tender mix, CSV export, and command.
Synthetic fixtures; current 2026-10-08..14, prior 10-01..07."""
import csv
import datetime
import io
import os
import shutil
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Sale
from checkout.prior_tender_mix import prior_tender_mix
from checkout.prior_tender_mix_export import (
    EXPORT_FIELDNAMES, export_prior_tender_mix,
    export_prior_tender_mix_csv)
from checkout.tender_mix import tender_mix
from saloncore.models import Salon

START = datetime.date(2026, 10, 8)
END = datetime.date(2026, 10, 14)
P_START = datetime.date(2026, 10, 1)
P_END = datetime.date(2026, 10, 7)


def _stamp(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)),
        datetime.timezone.utc)


class PriorTenderMixTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self._pay(self.salon, "cash", "50.00", datetime.date(2026, 10, 3))
        self._pay(self.salon, "external", "50.00", datetime.date(2026, 10, 5))
        self._pay(self.salon, "cash", "100.00", START)
        self._pay(self.salon, "external", "50.00", END)
        self._pay(self.other, "cash", "999.00", START)
        self._pay(self.salon, "cash", "999.00", datetime.date(2026, 9, 30))

    def _pay(self, salon, method, amount, day):
        sale = Sale.objects.create(
            salon=salon, status=Sale.Status.COMPLETED, completed_at=_stamp(day))
        payment = Payment.objects.create(
            sale=sale, method=method, amount=Decimal(amount),
            status=Payment.Status.COMPLETED)
        stamp = _stamp(day)
        Payment.objects.filter(pk=payment.pk).update(
            created_at=stamp, updated_at=stamp)
        return payment

    def test_both_windows_verbatim(self):
        result = prior_tender_mix(self.salon, START, END)
        cur = tender_mix(self.salon, START, END)
        pri = tender_mix(self.salon, P_START, P_END)
        self.assertEqual((result.prior_start, result.prior_end), (P_START, P_END))
        self.assertEqual(result.current, cur)
        self.assertEqual(result.prior, pri)
        for entry in result.entries:
            self.assertEqual(entry.current, cur[entry.method].total)
            self.assertEqual(entry.prior, pri[entry.method].total)
            self.assertEqual(
                entry.current_share_percent, cur[entry.method].share_percent)
            self.assertEqual(
                entry.prior_share_percent, pri[entry.method].share_percent)
        self.assertEqual((result.current_total, result.prior_total),
                         (Decimal("150.00"), Decimal("100.00")))
        self.assertEqual(result.salon_id, self.salon.pk)

    def test_delta_and_percent_change(self):
        result = prior_tender_mix(self.salon, START, END)
        cash, ext = result["cash"], result["external"]
        self.assertEqual((cash.current, cash.prior, cash.delta),
                         (Decimal("100.00"), Decimal("50.00"), Decimal("50.00")))
        self.assertEqual(cash.percent_change, Decimal("100.00"))
        self.assertEqual((cash.current_share_percent, cash.prior_share_percent),
                         (Decimal("66.67"), Decimal("50.00")))
        self.assertEqual((ext.delta, ext.percent_change),
                         (Decimal("0.00"), Decimal("0.00")))
        self.assertEqual((result.total_delta, result.total_percent_change),
                         (Decimal("50.00"), Decimal("50.00")))

    def test_count_delta_verbatim(self):
        result = prior_tender_mix(self.salon, START, END)
        cur = tender_mix(self.salon, START, END)
        pri = tender_mix(self.salon, P_START, P_END)
        # Verbatim from tender_mix: 2 payments in each window.
        self.assertEqual(result.count.current, cur.count)
        self.assertEqual(result.count.prior, pri.count)
        self.assertEqual((result.count.current, result.count.prior,
                          result.count.delta, result.count.percent_change),
                         (2, 2, 0, Decimal("0.00")))
        self.assertEqual(result.count.component, "count")
        self.assertIsInstance(result.count.current, int)
        self.assertIsInstance(result.count.delta, int)
        self.assertEqual(result.payment_count, result.count)
        self.assertEqual((result.current_count, result.prior_count), (2, 2))
        self.assertEqual(result.count.as_dict()["delta"], 0)
        for entry in result.entries:
            self.assertFalse(hasattr(entry, "count"))
            self.assertFalse(hasattr(entry, "payment_count"))

    def test_none_when_prior_total_zero(self):
        result = prior_tender_mix(
            self.salon, datetime.date(2026, 9, 24), datetime.date(2026, 9, 30))
        self.assertEqual(result.prior_total, Decimal("0.00"))
        self.assertEqual(result.current_total, Decimal("999.00"))
        for entry in result.entries:
            self.assertIsNone(entry.prior_share_percent)
            self.assertIsNone(entry.percent_change)
        self.assertIsNone(result.total_percent_change)
        self.assertEqual((result.count.current, result.count.prior,
                          result.count.delta), (1, 0, 1))
        self.assertIsNone(result.count.percent_change)
        text = export_prior_tender_mix_csv(
            self.salon, datetime.date(2026, 9, 24), datetime.date(2026, 9, 30))
        for row in csv.DictReader(io.StringIO(text)):
            self.assertEqual(row["percent_change"], "")
            self.assertEqual(row["prior_share_percent"], "")
            self.assertEqual(row["count_delta"], "1")
            self.assertEqual(row["count_percent_change"], "")
        empty = prior_tender_mix(
            self.salon, datetime.date(2026, 8, 8), datetime.date(2026, 8, 14))
        for entry in empty.entries:
            self.assertIsNone(entry.current_share_percent)
            self.assertIsNone(entry.prior_share_percent)

    def test_reversed_and_missing_raise(self):
        with self.assertRaises(ValueError):
            prior_tender_mix(self.salon, END, START)
        with self.assertRaises(ValueError):
            prior_tender_mix(None, START, END)
        with self.assertRaises(ValueError):
            prior_tender_mix(self.salon, START, None)

    def test_csv_rows_match_service(self):
        result = prior_tender_mix(self.salon, START, END)
        rows = export_prior_tender_mix(self.salon, START, END)
        self.assertEqual([list(r) for r in rows],
                         [EXPORT_FIELDNAMES] * len(rows))
        cash = rows[0]
        self.assertEqual(cash["method"], "cash")
        self.assertEqual(
            (cash["current"], cash["prior"], cash["delta"],
             cash["percent_change"], cash["current_share_percent"],
             cash["prior_share_percent"]),
            ("100.00", "50.00", "50.00", "100.00", "66.67", "50.00"))
        self.assertEqual(
            (cash["start"], cash["prior_start"], cash["prior_end"]),
            (START.isoformat(), P_START.isoformat(), P_END.isoformat()))
        self.assertEqual(
            (cash["current_count"], cash["prior_count"],
             cash["count_delta"], cash["count_percent_change"]),
            (2, 2, 0, "0.00"))
        self.assertEqual(cash["count_delta"], result.count.delta)
        text = export_prior_tender_mix_csv(self.salon, START, END)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [{**r, "salon_id": int(r["salon_id"]),
              "current_count": int(r["current_count"]),
              "prior_count": int(r["prior_count"]),
              "count_delta": int(r["count_delta"])} for r in parsed], rows)
        self.assertEqual(result["cash"].delta, Decimal(cash["delta"]))

    def test_command_stdout_and_file_match_service(self):
        out = io.StringIO()
        call_command("export_prior_tender_mix", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        expected = export_prior_tender_mix_csv(self.salon, START, END)
        self.assertEqual(out.getvalue(), expected)
        tmp = os.path.join(os.getcwd(), "tmp_prior_tender_test")
        os.makedirs(tmp, exist_ok=True)
        try:
            path = os.path.join(tmp, "prior.csv")
            call_command("export_prior_tender_mix", salon_id=self.salon.pk,
                         start_date=START.isoformat(), end_date=END.isoformat(),
                         output=path, stdout=io.StringIO())
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), expected)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_command_errors(self):
        bad = os.path.join(os.getcwd(), "no_such_dir_prior", "x.csv")
        cases = [
            dict(salon_id=self.salon.pk + 999, start_date=START, end_date=END),
            dict(salon_id=self.salon.pk, start_date="not-a-date", end_date=END),
            dict(salon_id=self.salon.pk),
            dict(salon_id=self.salon.pk, start_date=END, end_date=START),
            dict(salon_id=self.salon.pk, start_date=START, end_date=END,
                 output=bad),
        ]
        for kwargs in cases:
            with self.assertRaises(CommandError):
                call_command("export_prior_tender_mix",
                             stdout=io.StringIO(), **kwargs)
