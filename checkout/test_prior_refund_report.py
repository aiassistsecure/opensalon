"""Tests for prior refund report, CSV export, and command.
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

from checkout.models import Payment, Refund, Sale, SaleItem
from checkout.prior_refund_report import prior_refund_report
from checkout.prior_refund_report_export import (
    EXPORT_FIELDNAMES, export_prior_refund_report,
    export_prior_refund_report_csv)
from checkout.refund_report import refund_totals
from checkout.refunds import record_refund
from saloncore.models import Salon

D = datetime.date
TD = datetime.timedelta
START, END = D(2026, 10, 8), D(2026, 10, 14)
P_START, P_END = D(2026, 10, 1), D(2026, 10, 7)


class PriorRefundReportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self._refund(self.salon, "20.00", "cash", P_START)
        self._refund(self.salon, "10.00", "external", P_START + TD(days=2))
        self._refund(self.salon, "50.00", "cash", START)
        self._refund(self.salon, "25.00", "cash", START + TD(days=1))
        self._refund(self.salon, "30.00", "external", START + TD(days=1))
        self._refund(self.other, "999.00", "cash", START)
        self._refund(self.other, "999.00", "cash", P_START)
        self._refund(self.salon, "999.00", "cash", D(2026, 9, 30))

    def _stamp(self, day, hour=12):
        return timezone.make_aware(datetime.datetime.combine(
            day, datetime.time(hour, 0)), datetime.timezone.utc)

    def _refund(self, salon, amount, tender, when):
        sale = Sale.objects.create(salon=salon, status=Sale.Status.COMPLETED,
                                   completed_at=timezone.now())
        price = max(Decimal(amount), Decimal("100.00"))
        SaleItem.objects.create(sale=sale, kind="service", description="Haircut",
                                unit_price=price)
        Payment.objects.create(sale=sale, method=tender,
                               amount=price,
                               status=Payment.Status.COMPLETED)
        refund = record_refund(sale, Decimal(amount), tender=tender)
        Refund.objects.filter(pk=refund.pk).update(
            created_at=self._stamp(when, 13))
        return refund

    def test_both_windows_verbatim(self):
        r = prior_refund_report(self.salon, START, END)
        cur = refund_totals(self.salon, START, END)
        pri = refund_totals(self.salon, P_START, P_END)
        self.assertEqual((r.start, r.end, r.date_from, r.date_to), (START, END, START, END))
        self.assertEqual((r.prior_start, r.prior_end), (P_START, P_END))
        self.assertEqual((r.current, r.prior), (cur, pri))
        self.assertEqual(r.salon_id, self.salon.pk)

    def test_total_deltas(self):
        r = prior_refund_report(self.salon, START, END)
        self.assertEqual((r.total.current, r.total.prior, r.total.delta, r.total.percent_change),
                         (Decimal("105.00"), Decimal("30.00"), Decimal("75.00"), Decimal("250.00")))
        self.assertEqual((r.refund_count.current, r.refund_count.prior,
                          r.refund_count.delta, r.refund_count.percent_change),
                         (3, 2, 1, Decimal("50.00")))

    def test_per_tender_deltas(self):
        r = prior_refund_report(self.salon, START, END)
        self.assertEqual([e.tender for e in r.entries], ["cash", "external"])
        cash, ext = r.entries
        self.assertEqual((cash.total.current, cash.total.prior, cash.total.delta,
                          cash.total.percent_change),
                         (Decimal("75.00"), Decimal("20.00"), Decimal("55.00"), Decimal("275.00")))
        self.assertEqual((cash.refund_count.current, cash.refund_count.prior,
                          cash.refund_count.delta), (2, 1, 1))
        self.assertEqual((ext.total.current, ext.total.prior, ext.total.delta),
                         (Decimal("30.00"), Decimal("10.00"), Decimal("20.00")))
        self.assertEqual((ext.refund_count.current, ext.refund_count.prior), (1, 1))
        self.assertEqual(r["cash"], cash)
        self.assertEqual(r.by_tender["external"], ext)

    def test_by_day_deltas_offset_aligned(self):
        r = prior_refund_report(self.salon, START, END)
        self.assertEqual(len(r.day_entries), 7)
        self.assertEqual([e.day for e in r.day_entries],
                         [START + TD(days=i) for i in range(7)])
        self.assertEqual([e.prior_day for e in r.day_entries],
                         [P_START + TD(days=i) for i in range(7)])
        d0, d1, d2 = r.day_entries[:3]
        self.assertEqual((d0.total.current, d0.total.prior, d0.total.delta, d0.total.percent_change),
                         (Decimal("50.00"), Decimal("20.00"), Decimal("30.00"), Decimal("150.00")))
        self.assertEqual((d1.total.current, d1.total.prior, d1.refund_count.current),
                         (Decimal("55.00"), Decimal("0.00"), 2))
        self.assertIsNone(d1.total.percent_change)
        self.assertEqual((d2.total.current, d2.total.prior, d2.total.delta, d2.refund_count.delta),
                         (Decimal("0.00"), Decimal("10.00"), Decimal("-10.00"), -1))
        self.assertEqual(r.by_day[START], d0)
        self.assertTrue(all(e.total.current == Decimal("0.00")
                            for e in r.day_entries[3:]))

    def test_prior_zero_and_empty_window(self):
        empty = prior_refund_report(self.salon, D(2026, 6, 1), D(2026, 6, 7))
        self.assertEqual((empty.total.current, empty.total.prior), (Decimal("0.00"), Decimal("0.00")))
        self.assertIsNone(empty.total.percent_change)
        self.assertIsNone(empty.refund_count.percent_change)
        self.assertEqual(len(empty.day_entries), 7)

    def test_salon_isolation(self):
        r = prior_refund_report(self.other, START, END)
        self.assertEqual((r.total.current, r.total.prior, r.total.delta),
                         (Decimal("999.00"), Decimal("999.00"), Decimal("0.00")))
        self.assertEqual(prior_refund_report(self.salon, START, END).total.current,
                         Decimal("105.00"))

    def test_reversed_and_missing_raise(self):
        for args in [(self.salon, END, START), (None, START, END),
                     (self.salon, START, None), (self.salon,)]:
            with self.assertRaises(ValueError):
                prior_refund_report(*args)

    def test_csv_rows_match_service(self):
        rows = export_prior_refund_report(self.salon, START, END)
        self.assertEqual([list(r) for r in rows], [EXPORT_FIELDNAMES] * len(rows))
        self.assertEqual(len(rows), 20)  # 2 totals + 2x2 tenders + 7x2 days
        self.assertEqual([r["figure"] for r in rows[:2]], ["refund_count", "total"])
        self.assertTrue(all(r["tender"] == "" and r["day"] == "" for r in rows[:2]))
        self.assertEqual((rows[0]["current"], rows[0]["prior"], rows[0]["delta"]), ("3", "2", "1"))
        self.assertEqual((rows[1]["current"], rows[1]["prior"], rows[1]["delta"],
                          rows[1]["percent_change"]), ("105.00", "30.00", "75.00", "250.00"))
        cash_total = [r for r in rows if r["tender"] == "cash" and r["figure"] == "total"][0]
        self.assertEqual((cash_total["current"], cash_total["prior"]), ("75.00", "20.00"))
        day_rows = [r for r in rows if r["day"]]
        self.assertEqual(len(day_rows), 14)
        self.assertEqual((day_rows[0]["day"], day_rows[0]["prior_day"]),
                         (START.isoformat(), P_START.isoformat()))
        self.assertEqual(day_rows[1]["percent_change"], "150.00")
        self.assertEqual(day_rows[3]["percent_change"], "")  # day1 total, prior zero
        text = export_prior_refund_report_csv(self.salon, START, END)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual([{**r, "salon_id": int(r["salon_id"])} for r in parsed], rows)

    def test_command_stdout_and_file_match_service(self):
        out = io.StringIO()
        call_command("export_prior_refund_report", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        expected = export_prior_refund_report_csv(self.salon, START, END)
        self.assertEqual(out.getvalue(), expected)
        tmp = os.path.join(os.getcwd(), "tmp_prior_refund_report_test")
        os.makedirs(tmp, exist_ok=True)
        try:
            path = os.path.join(tmp, "prior.csv")
            call_command("export_prior_refund_report", salon_id=self.salon.pk,
                         start_date=START.isoformat(), end_date=END.isoformat(),
                         output=path, stdout=io.StringIO())
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), expected)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_command_errors(self):
        bad = os.path.join(os.getcwd(), "no_such_dir_prior_refund", "x.csv")
        cases = [
            dict(salon_id=self.salon.pk + 999, start_date=START, end_date=END),
            dict(salon_id=self.salon.pk, start_date="not-a-date", end_date=END),
            dict(salon_id=self.salon.pk),
            dict(salon_id=self.salon.pk, start_date=END, end_date=START),
            dict(salon_id=self.salon.pk, start_date=START, end_date=END, output=bad),
        ]
        for kwargs in cases:
            with self.assertRaises(CommandError):
                call_command("export_prior_refund_report", stdout=io.StringIO(), **kwargs)
