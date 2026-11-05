"""Tests for prior tender totals, CSV export, and command.
Synthetic fixtures; current 2026-10-08..14, prior 10-01..07."""
import csv
import datetime
import io
import json
import os
import shutil
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Sale
from checkout.prior_tender_totals import prior_tender_totals
from checkout.prior_tender_totals_export import (
    EXPORT_FIELDNAMES, export_prior_tender_totals,
    export_prior_tender_totals_csv)
from checkout.tender_totals import tender_totals
from saloncore.models import Salon

START = datetime.date(2026, 10, 8)
END = datetime.date(2026, 10, 14)
P_START = datetime.date(2026, 10, 1)
P_END = datetime.date(2026, 10, 7)


def _stamp(day, hour=12):
    return timezone.make_aware(datetime.datetime.combine(
        day, datetime.time(hour, 0)), datetime.timezone.utc)


class PriorTenderTotalsTests(TestCase):
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
        sale = Sale.objects.create(salon=salon, status=Sale.Status.COMPLETED,
                                   completed_at=_stamp(day))
        payment = Payment.objects.create(sale=sale, method=method,
            amount=Decimal(amount), status=Payment.Status.COMPLETED)
        stamp = _stamp(day)
        Payment.objects.filter(pk=payment.pk).update(created_at=stamp, updated_at=stamp)
        return payment

    def test_period_math_and_both_windows_verbatim(self):
        result = prior_tender_totals(START, END, salon=self.salon)
        self.assertEqual((result.prior_start, result.prior_end), (P_START, P_END))
        self.assertEqual(result.current, tender_totals(START, END, salon=self.salon))
        self.assertEqual(result.prior, tender_totals(P_START, P_END, salon=self.salon))
        self.assertEqual((result.current_total, result.prior_total),
                         (Decimal("150.00"), Decimal("100.00")))
        self.assertEqual((result.total.current, result.total.prior,
                          result.total.delta, result.total.percent_change),
                         (Decimal("150.00"), Decimal("100.00"),
                          Decimal("50.00"), Decimal("50.00")))
        self.assertEqual(result.salon_id, self.salon.pk)
        # Salon-first form, mirroring prior_tender_mix, agrees.
        self.assertEqual(prior_tender_totals(self.salon, START, END), result)

    def test_datetime_window_shifts_by_duration(self):
        start = _stamp(START, 9)
        end = _stamp(END, 9)
        result = prior_tender_totals(start, end, salon=self.salon)
        self.assertEqual(result.prior_start, start - (end - start))
        self.assertEqual(result.prior_end, end - (end - start))
        self.assertEqual(result.prior,
                         tender_totals(result.prior_start, result.prior_end,
                                       salon=self.salon))

    def test_delta_percent_and_count(self):
        result = prior_tender_totals(START, END, salon=self.salon)
        cash, ext = result["cash"], result["external"]
        self.assertEqual((cash.current, cash.prior, cash.delta, cash.percent_change),
                         (Decimal("100.00"), Decimal("50.00"),
                          Decimal("50.00"), Decimal("100.00")))
        self.assertEqual((ext.delta, ext.percent_change),
                         (Decimal("0.00"), Decimal("0.00")))
        self.assertEqual((result.count.current, result.count.prior,
                          result.count.delta, result.count.percent_change),
                         (2, 2, 0, Decimal("0.00")))
        self.assertEqual((result.current_count, result.prior_count), (2, 2))

    def test_unscoped_includes_all_salons(self):
        result = prior_tender_totals(START, END)
        self.assertIsNone(result.salon)
        self.assertEqual(result.current_total, Decimal("1149.00"))
        self.assertEqual(result.prior_total, Decimal("100.00"))

    def test_empty_prior_period(self):
        result = prior_tender_totals(
            datetime.date(2026, 9, 24), datetime.date(2026, 9, 30),
            salon=self.salon)
        self.assertEqual(result.prior_total, Decimal("0.00"))
        self.assertEqual(result.prior.count, 0)
        self.assertEqual(result.prior.by_method,
                         {"cash": Decimal("0.00"), "external": Decimal("0.00")})
        self.assertEqual(result.current_total, Decimal("999.00"))
        for entry in result.entries:
            self.assertIsNone(entry.percent_change)
        self.assertIsNone(result.total_percent_change)
        self.assertIsNone(result.count.percent_change)
        self.assertEqual((result.count.current, result.count.delta), (1, 1))
        text = export_prior_tender_totals_csv(
            datetime.date(2026, 9, 24), datetime.date(2026, 9, 30),
            salon=self.salon)
        for row in csv.DictReader(io.StringIO(text)):
            self.assertEqual(row["percent_change"], "")
            self.assertEqual(row["count_percent_change"], "")
            self.assertEqual(row["prior"], "0.00")

    def test_reversed_and_missing_raise(self):
        with self.assertRaises(ValueError):
            prior_tender_totals(END, START, salon=self.salon)
        with self.assertRaises(ValueError):
            prior_tender_totals(START, None, salon=self.salon)
        with self.assertRaises(ValueError):
            prior_tender_totals(None, END)

    def test_csv_rows_match_service(self):
        result = prior_tender_totals(START, END, salon=self.salon)
        rows = export_prior_tender_totals(START, END, salon=self.salon)
        self.assertEqual([list(r) for r in rows],
                         [EXPORT_FIELDNAMES] * len(rows))
        cash = rows[0]
        self.assertEqual(cash["method"], "cash")
        self.assertEqual(
            (cash["current"], cash["prior"], cash["delta"],
             cash["percent_change"]),
            ("100.00", "50.00", "50.00", "100.00"))
        self.assertEqual(
            (cash["start"], cash["prior_start"], cash["prior_end"]),
            (START.isoformat(), P_START.isoformat(), P_END.isoformat()))
        self.assertEqual(
            (cash["current_count"], cash["prior_count"],
             cash["count_delta"], cash["count_percent_change"]),
            (2, 2, 0, "0.00"))
        self.assertEqual(result["cash"].delta, Decimal(cash["delta"]))
        # Salon-first export form agrees.
        self.assertEqual(export_prior_tender_totals(self.salon, START, END), rows)
        text = export_prior_tender_totals_csv(START, END, salon=self.salon)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [{**r, "salon_id": int(r["salon_id"]),
              "current_count": int(r["current_count"]),
              "prior_count": int(r["prior_count"]),
              "count_delta": int(r["count_delta"])} for r in parsed], rows)

    def test_command_stdout_and_file_match_service(self):
        out = io.StringIO()
        call_command("export_prior_tender_totals", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        expected = export_prior_tender_totals_csv(self.salon, START, END)
        self.assertEqual(out.getvalue(), expected)
        tmp = os.path.join(os.getcwd(), "tmp_prior_totals_test")
        os.makedirs(tmp, exist_ok=True)
        try:
            path = os.path.join(tmp, "prior.csv")
            call_command("export_prior_tender_totals", salon_id=self.salon.pk,
                         start_date=START.isoformat(), end_date=END.isoformat(),
                         output=path, stdout=io.StringIO())
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), expected)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_command_default_format_is_csv(self):
        out = io.StringIO()
        call_command("export_prior_tender_totals", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_tender_totals_csv(self.salon, START, END))

    def test_command_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_tender_totals", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_tender_totals_csv(self.salon, START, END))

    def test_command_json_matches_service_rows(self):
        out = io.StringIO()
        call_command("export_prior_tender_totals", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="json", stdout=out)
        rows = export_prior_tender_totals(self.salon, START, END)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(out.getvalue(), json.dumps(
            rows, indent=2, cls=DjangoJSONEncoder) + "\n")
        text = export_prior_tender_totals_csv(self.salon, START, END)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [{**r, "salon_id": int(r["salon_id"]),
              "current_count": int(r["current_count"]),
              "prior_count": int(r["prior_count"]),
              "count_delta": int(r["count_delta"])} for r in parsed],
            json.loads(out.getvalue()))

    def test_command_json_file_matches_service_rows(self):
        tmp = tempfile.mkdtemp(prefix="tmp_prior_tender_totals_json_test")
        try:
            path = os.path.join(tmp, "prior.json")
            call_command("export_prior_tender_totals", salon_id=self.salon.pk,
                         start_date=START.isoformat(), end_date=END.isoformat(),
                         format="json", output=path, stdout=io.StringIO())
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh),
                                 export_prior_tender_totals(self.salon, START, END))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_command_unknown_format_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_tender_totals", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="xml",
                         stdout=io.StringIO())

    def test_command_errors(self):
        bad = os.path.join(os.getcwd(), "no_such_dir_prior_totals", "x.csv")
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
                call_command("export_prior_tender_totals",
                             stdout=io.StringIO(), **kwargs)
