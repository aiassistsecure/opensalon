"""Tests for prior cashup detail, CSV export, and command.
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
from django.test import TestCase
from django.utils import timezone

from checkout.cashup_detail import cashup_detail
from checkout.models import Payment, Refund, Sale, SaleItem
from checkout.prior_cashup_detail import prior_cashup_detail
from checkout.prior_cashup_detail_export import (
    EXPORT_FIELDNAMES, export_prior_cashup_detail,
    export_prior_cashup_detail_csv)
from checkout.refunds import record_refund
from checkout.void import void_sale
from saloncore.models import Salon

D = datetime.date
TD = datetime.timedelta
START, END = D(2026, 10, 8), D(2026, 10, 14)
P_START, P_END = D(2026, 10, 1), D(2026, 10, 7)


class PriorCashupDetailTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        sale = self._sale(self.salon, "cash", "100.00", P_START + TD(days=1))
        self._refund(sale, "20.00", "cash", P_START + TD(days=1))
        self._sale(self.salon, "external", "40.00", P_START + TD(days=2))
        self._voided(self.salon, "cash", "30.00", P_START + TD(days=3))
        sale = self._sale(self.salon, "cash", "200.00", START)
        self._refund(sale, "50.00", "cash", START)
        self._sale(self.salon, "external", "80.00", START + TD(days=1))
        self._voided(self.salon, "external", "25.00", START + TD(days=2))
        self._sale(self.other, "cash", "999.00", START)
        self._sale(self.other, "cash", "999.00", P_START)
        self._sale(self.salon, "cash", "999.00", D(2026, 9, 30))

    def _stamp(self, day, hour=12):
        return timezone.make_aware(datetime.datetime.combine(
            day, datetime.time(hour, 0)), datetime.timezone.utc)

    def _sale(self, salon, method, amount, when):
        sale = Sale.objects.create(salon=salon, status=Sale.Status.COMPLETED,
                                   completed_at=timezone.now())
        SaleItem.objects.create(sale=sale, kind="service", description="Haircut",
                                unit_price=Decimal(amount))
        payment = Payment.objects.create(sale=sale, method=method,
                                         amount=Decimal(amount),
                                         status=Payment.Status.COMPLETED)
        stamp = self._stamp(when)
        Payment.objects.filter(pk=payment.pk).update(created_at=stamp)
        Sale.objects.filter(pk=sale.pk).update(created_at=stamp)
        return sale

    def _refund(self, sale, amount, tender, when):
        refund = record_refund(sale, Decimal(amount), tender=tender)
        Refund.objects.filter(pk=refund.pk).update(created_at=self._stamp(when, 13))
        return refund

    def _voided(self, salon, method, amount, when):
        sale = self._sale(salon, method, amount, when)
        void_sale(sale, "entered in error")
        return sale

    def test_both_windows_verbatim(self):
        r = prior_cashup_detail(self.salon, START, END)
        cur, pri = cashup_detail(self.salon, START, END), cashup_detail(self.salon, P_START, P_END)
        self.assertEqual((r.start, r.end, r.date_from, r.date_to), (START, END, START, END))
        self.assertEqual((r.prior_start, r.prior_end), (P_START, P_END))
        self.assertEqual((r.current, r.prior), (cur, pri))
        self.assertEqual((r.current_detail, r.prior_detail), (cur, pri))
        self.assertEqual(r.salon_id, self.salon.pk)

    def test_total_deltas(self):
        r = prior_cashup_detail(self.salon, START, END)
        self.assertEqual((r.gross.current, r.gross.prior, r.gross.delta, r.gross.percent_change),
                         (Decimal("280.00"), Decimal("140.00"), Decimal("140.00"), Decimal("100.00")))
        self.assertEqual((r.refunds.current, r.refunds.prior, r.refunds.delta, r.refunds.percent_change),
                         (Decimal("50.00"), Decimal("20.00"), Decimal("30.00"), Decimal("150.00")))
        self.assertEqual((r.voids.current, r.voids.prior, r.voids.delta),
                         (Decimal("25.00"), Decimal("30.00"), Decimal("-5.00")))
        self.assertEqual((r.net.current, r.net.prior, r.net.delta, r.net.percent_change),
                         (Decimal("230.00"), Decimal("120.00"), Decimal("110.00"), Decimal("91.67")))
        self.assertEqual((r.payment_count.current, r.payment_count.prior, r.payment_count.delta), (2, 2, 0))
        self.assertEqual((r.refund_count.current, r.refund_count.prior), (1, 1))
        self.assertEqual((r.void_count.current, r.void_count.prior), (1, 1))

    def test_per_tender_deltas(self):
        r = prior_cashup_detail(self.salon, START, END)
        self.assertEqual([e.tender for e in r.entries], ["cash", "external"])
        cash, ext = r.entries
        self.assertEqual((cash.gross.current, cash.gross.prior, cash.gross.delta),
                         (Decimal("200.00"), Decimal("100.00"), Decimal("100.00")))
        self.assertEqual((cash.refunds.current, cash.refunds.prior), (Decimal("50.00"), Decimal("20.00")))
        self.assertEqual((cash.voids.current, cash.voids.prior, cash.voids.delta, cash.voids.percent_change),
                         (Decimal("0.00"), Decimal("30.00"), Decimal("-30.00"), Decimal("-100.00")))
        self.assertEqual((cash.net.current, cash.net.prior, cash.net.percent_change),
                         (Decimal("150.00"), Decimal("80.00"), Decimal("87.50")))
        self.assertEqual((cash.void_count.current, cash.void_count.prior, cash.void_count.delta), (0, 1, -1))
        self.assertEqual((ext.gross.current, ext.gross.prior, ext.net.current, ext.net.prior),
                         (Decimal("80.00"), Decimal("40.00"), Decimal("80.00"), Decimal("40.00")))
        self.assertEqual((ext.voids.current, ext.payment_count.current), (Decimal("25.00"), 1))
        self.assertEqual(r["cash"], cash); self.assertEqual(r.by_tender["external"], ext)

    def test_prior_zero_handling(self):
        ext = prior_cashup_detail(self.salon, START, END).by_tender["external"]
        self.assertIsNone(ext.refunds.percent_change)
        self.assertEqual(ext.refunds.delta, Decimal("0.00"))
        self.assertIsNone(ext.voids.percent_change)
        self.assertEqual(ext.voids.delta, Decimal("25.00"))
        self.assertIsNone(ext.refund_count.percent_change)
        self.assertIsNone(ext.void_count.percent_change)
        empty = prior_cashup_detail(self.salon, D(2026, 6, 1), D(2026, 6, 7))
        self.assertEqual((empty.gross.current, empty.gross.prior), (Decimal("0.00"), Decimal("0.00")))
        self.assertIsNone(empty.gross.percent_change)
        self.assertIsNone(empty.payment_count.percent_change)

    def test_salon_isolation(self):
        r = prior_cashup_detail(self.other, START, END)
        self.assertEqual((r.gross.current, r.gross.prior, r.gross.delta),
                         (Decimal("999.00"), Decimal("999.00"), Decimal("0.00")))
        self.assertEqual(prior_cashup_detail(self.salon, START, END).gross.current, Decimal("280.00"))

    def test_reversed_and_missing_raise(self):
        for args in [(self.salon, END, START), (None, START, END),
                     (self.salon, START, None), (self.salon,)]:
            with self.assertRaises(ValueError):
                prior_cashup_detail(*args)

    def test_csv_rows_match_service(self):
        rows = export_prior_cashup_detail(self.salon, START, END)
        self.assertEqual([list(r) for r in rows], [EXPORT_FIELDNAMES] * len(rows))
        self.assertEqual(len(rows), 21)  # 7 totals + 7 x 2 tenders
        self.assertEqual([r["figure"] for r in rows[:7]],
                         ["gross", "refunds", "voids", "net", "payment_count", "refund_count", "void_count"])
        self.assertTrue(all(r["tender"] == "" for r in rows[:7]))
        self.assertEqual({r["tender"] for r in rows[7:]}, {"cash", "external"})
        gross = rows[0]
        self.assertEqual((gross["current"], gross["prior"], gross["delta"], gross["percent_change"]),
                         ("280.00", "140.00", "140.00", "100.00"))
        self.assertEqual((rows[4]["current"], rows[4]["prior"], rows[4]["delta"]), ("2", "2", "0"))
        ext_voids = [r for r in rows if r["tender"] == "external" and r["figure"] == "voids"][0]
        self.assertEqual((ext_voids["current"], ext_voids["prior"], ext_voids["delta"], ext_voids["percent_change"]),
                         ("25.00", "0.00", "25.00", ""))
        self.assertEqual((gross["start"], gross["prior_start"], gross["prior_end"]),
                         (START.isoformat(), P_START.isoformat(), P_END.isoformat()))
        text = export_prior_cashup_detail_csv(self.salon, START, END)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual([{**r, "salon_id": int(r["salon_id"])} for r in parsed], rows)

    def test_command_stdout_and_file_match_service(self):
        out = io.StringIO()
        call_command("export_prior_cashup_detail", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        expected = export_prior_cashup_detail_csv(self.salon, START, END)
        self.assertEqual(out.getvalue(), expected)
        tmp = os.path.join(os.getcwd(), "tmp_prior_cashup_detail_test")
        os.makedirs(tmp, exist_ok=True)
        try:
            path = os.path.join(tmp, "prior.csv")
            call_command("export_prior_cashup_detail", salon_id=self.salon.pk,
                         start_date=START.isoformat(), end_date=END.isoformat(),
                         output=path, stdout=io.StringIO())
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), expected)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_command_errors(self):
        bad = os.path.join(os.getcwd(), "no_such_dir_prior_detail", "x.csv")
        cases = [
            dict(salon_id=self.salon.pk + 999, start_date=START, end_date=END),
            dict(salon_id=self.salon.pk, start_date="not-a-date", end_date=END),
            dict(salon_id=self.salon.pk),
            dict(salon_id=self.salon.pk, start_date=END, end_date=START),
            dict(salon_id=self.salon.pk, start_date=START, end_date=END, output=bad),
        ]
        for kwargs in cases:
            with self.assertRaises(CommandError):
                call_command("export_prior_cashup_detail", stdout=io.StringIO(), **kwargs)

    def test_command_default_format_is_csv(self):
        out = io.StringIO()
        call_command("export_prior_cashup_detail", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_cashup_detail_csv(self.salon, START, END))

    def test_command_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_cashup_detail", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_cashup_detail_csv(self.salon, START, END))

    def test_command_json_matches_service_rows(self):
        out = io.StringIO()
        call_command("export_prior_cashup_detail", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="json", stdout=out)
        rows = export_prior_cashup_detail(self.salon, START, END)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(out.getvalue(), json.dumps(rows, indent=2) + "\n")

    def test_command_json_file_matches_service_rows(self):
        tmp = tempfile.mkdtemp(prefix="tmp_prior_cashup_detail_json_test")
        try:
            path = os.path.join(tmp, "prior.json")
            call_command("export_prior_cashup_detail", salon_id=self.salon.pk,
                         start_date=START.isoformat(), end_date=END.isoformat(),
                         format="json", output=path, stdout=io.StringIO())
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh),
                                 export_prior_cashup_detail(self.salon, START, END))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_command_unknown_format_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_cashup_detail", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="xml",
                         stdout=io.StringIO())
