import csv
import datetime
import io
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from checkout.cashup_detail import cashup_detail
from checkout.cashup_detail_export import (
    EXPORT_FIELDNAMES,
    cashup_detail_csv,
    export_cashup_detail,
    export_cashup_detail_csv,
)
from checkout.models import Payment, Refund, Sale, SaleItem
from checkout.refunds import record_refund
from checkout.void import void_sale
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class CashupDetailExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def _completed_sale(self, salon, method, amount, when=None):
        sale = Sale.objects.create(
            salon=salon, status=Sale.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal(amount),
        )
        payment = Payment.objects.create(
            sale=sale, method=method, amount=Decimal(amount),
            status=Payment.Status.COMPLETED,
        )
        if when is not None:
            stamp = timezone.make_aware(
                datetime.datetime.combine(when, datetime.time(12, 0))
            )
            Payment.objects.filter(pk=payment.pk).update(created_at=stamp)
            Sale.objects.filter(pk=sale.pk).update(created_at=stamp)
        return sale

    def _refund_on(self, sale, amount, tender, when):
        refund = record_refund(sale, Decimal(amount), tender=tender)
        stamp = timezone.make_aware(
            datetime.datetime.combine(when, datetime.time(13, 0))
        )
        Refund.objects.filter(pk=refund.pk).update(created_at=stamp)
        return refund

    def _scenario(self):
        sale = self._completed_sale(self.salon, "cash", "100.00", when=DAY)
        self._refund_on(sale, "20.00", "cash", DAY)
        self._completed_sale(self.salon, "external", "50.00", when=DAY)
        voided = self._completed_sale(
            self.salon, "cash", "60.00", when=DAY)
        void_sale(voided, "entered in error")

    def test_csv_header_and_row_keys(self):
        text = export_cashup_detail_csv(self.salon, DAY, DAY)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        rows = export_cashup_detail(self.salon, DAY, DAY)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(list(row), EXPORT_FIELDNAMES)
        parsed = _rows(text)
        self.assertEqual(list(parsed[0]), EXPORT_FIELDNAMES)

    def test_row_values_match_service_output(self):
        self._scenario()
        detail = cashup_detail(self.salon, DAY, DAY)
        rows = export_cashup_detail(self.salon, DAY, DAY)
        expected = [
            {
                "salon_id": detail.salon_id,
                "date_from": detail.date_from.isoformat(),
                "date_to": detail.date_to.isoformat(),
                "tender": td.tender,
                "gross": str(td.gross.quantize(Decimal("0.01"))),
                "refunds": str(td.refunds.quantize(Decimal("0.01"))),
                "voids": str(td.voids.quantize(Decimal("0.01"))),
                "net": str(td.net.quantize(Decimal("0.01"))),
                "payment_count": td.payment_count,
                "refund_count": td.refund_count,
                "void_count": td.void_count,
            }
            for td in detail.by_tender.values()
        ]
        self.assertEqual(rows, expected)
        by_tender = {r["tender"]: r for r in rows}
        self.assertEqual(by_tender["cash"]["gross"], "100.00")
        self.assertEqual(by_tender["cash"]["refunds"], "20.00")
        self.assertEqual(by_tender["cash"]["voids"], "60.00")
        self.assertEqual(by_tender["cash"]["net"], "80.00")
        self.assertEqual(by_tender["cash"]["payment_count"], 1)
        self.assertEqual(by_tender["cash"]["refund_count"], 1)
        self.assertEqual(by_tender["cash"]["void_count"], 1)
        self.assertEqual(by_tender["external"]["net"], "50.00")
        # Per-tender rows sum to the service's own totals.
        self.assertEqual(
            sum(Decimal(r["gross"]) for r in rows), detail.gross)
        self.assertEqual(
            sum(Decimal(r["net"]) for r in rows), detail.net)

    def test_delegates_to_service_verbatim(self):
        with mock.patch(
            "checkout.cashup_detail_export.cashup_detail",
            wraps=cashup_detail,
        ) as spy:
            export_cashup_detail(self.salon, DAY, DAY)
        spy.assert_called_once_with(self.salon, DAY, DAY)

    def test_csv_agrees_with_list_and_alias(self):
        self._scenario()
        text = export_cashup_detail_csv(self.salon, DAY, DAY)
        parsed = [
            {
                **r,
                "salon_id": int(r["salon_id"]),
                "payment_count": int(r["payment_count"]),
                "refund_count": int(r["refund_count"]),
                "void_count": int(r["void_count"]),
            }
            for r in _rows(text)
        ]
        self.assertEqual(parsed, export_cashup_detail(self.salon, DAY, DAY))
        self.assertEqual(cashup_detail_csv(self.salon, DAY, DAY), text)

    def test_salon_scoping_matches_service(self):
        self._completed_sale(self.salon, "cash", "85.00", when=DAY)
        self._completed_sale(self.other, "cash", "999.00", when=DAY)
        detail = cashup_detail(self.salon, DAY, DAY)
        rows = export_cashup_detail(self.salon, DAY, DAY)
        for row in rows:
            self.assertEqual(row["salon_id"], self.salon.pk)
        cash = {r["tender"]: r for r in rows}["cash"]
        self.assertEqual(Decimal(cash["gross"]), detail.gross)
        self.assertEqual(cash["gross"], "85.00")

    def test_empty_range_zero_filled_rows(self):
        rows = export_cashup_detail(self.salon, DAY, DAY)
        self.assertEqual(
            [r["tender"] for r in rows], list(Payment.Method.values))
        for row in rows:
            self.assertEqual(row["gross"], "0.00")
            self.assertEqual(row["refunds"], "0.00")
            self.assertEqual(row["voids"], "0.00")
            self.assertEqual(row["net"], "0.00")
            self.assertEqual(row["payment_count"], 0)
            self.assertEqual(row["refund_count"], 0)
            self.assertEqual(row["void_count"], 0)
        parsed = _rows(export_cashup_detail_csv(self.salon, DAY, DAY))
        self.assertEqual(len(parsed), len(Payment.Method.values))

    def test_service_errors_propagate(self):
        with self.assertRaises(ValueError):
            export_cashup_detail(None, DAY, DAY)
        with self.assertRaises(ValueError):
            export_cashup_detail(
                self.salon, DAY + datetime.timedelta(days=1), DAY)
        with self.assertRaises(ValueError):
            export_cashup_detail_csv(None, DAY, DAY)

    def test_read_only_records_unchanged(self):
        self._scenario()
        before = (
            Payment.objects.count(), Sale.objects.count(),
            SaleItem.objects.count(), Refund.objects.count(),
        )
        export_cashup_detail(self.salon, DAY, DAY)
        export_cashup_detail_csv(self.salon, DAY, DAY)
        after = (
            Payment.objects.count(), Sale.objects.count(),
            SaleItem.objects.count(), Refund.objects.count(),
        )
        self.assertEqual(after, before)
