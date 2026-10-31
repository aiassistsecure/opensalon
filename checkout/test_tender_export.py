import csv
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Cashup, Payment, Sale, SaleItem
from checkout.tender_export import (
    EXPORT_FIELDNAMES,
    export_tender_totals,
    export_tender_totals_csv,
    tender_totals_csv,
)
from checkout.tender_totals import tender_totals, totals_by_tender
from saloncore.models import Salon


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class TenderExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        now = timezone.now()
        self.since = now - timezone.timedelta(hours=1)
        self.until = now + timezone.timedelta(hours=1)

    def _pay(self, salon, method, amount, status="completed",
             sale_status="completed"):
        sale = Sale.objects.create(
            salon=salon, status=sale_status, completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal(amount),
        )
        return Payment.objects.create(
            sale=sale, method=method, amount=Decimal(amount), status=status,
        )

    def test_csv_header_and_row_keys(self):
        text = export_tender_totals_csv(self.since, self.until)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        rows = export_tender_totals(self.since, self.until)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(list(row), EXPORT_FIELDNAMES)
        parsed = _rows(text)
        self.assertEqual(list(parsed[0]), EXPORT_FIELDNAMES)

    def test_row_values_match_service_output(self):
        self._pay(self.salon, "cash", "85.00")
        self._pay(self.salon, "cash", "15.00")
        self._pay(self.salon, "external", "50.00")
        self._pay(self.salon, "cash", "999.00", status="pending")
        totals = tender_totals(self.since, self.until)
        self.assertEqual(
            totals_by_tender(self.since, self.until), totals.by_method)
        rows = export_tender_totals(self.since, self.until)
        expected = [
            {
                "salon_id": None,
                "start": self.since.isoformat(),
                "end": self.until.isoformat(),
                "method": method,
                "amount": str(amount.quantize(Decimal("0.01"))),
                "total": str(totals.total.quantize(Decimal("0.01"))),
                "count": totals.count,
            }
            for method, amount in totals.by_method.items()
        ]
        self.assertEqual(rows, expected)
        self.assertEqual(totals.total, Decimal("150.00"))
        self.assertEqual(totals.count, 3)
        self.assertEqual(
            sum(Decimal(r["amount"]) for r in rows), totals.total)

    def test_csv_agrees_with_list_and_alias(self):
        self._pay(self.salon, "cash", "85.00")
        text = export_tender_totals_csv(self.since, self.until)
        parsed = [
            {
                **r,
                "salon_id": int(r["salon_id"]) if r["salon_id"] else None,
                "count": int(r["count"]),
            }
            for r in _rows(text)
        ]
        self.assertEqual(parsed, export_tender_totals(self.since, self.until))
        self.assertEqual(
            tender_totals_csv(self.since, self.until), text)

    def test_salon_scoping_matches_service(self):
        self._pay(self.salon, "cash", "85.00")
        self._pay(self.other, "cash", "40.00")
        self._pay(self.other, "external", "10.00")
        totals = tender_totals(self.since, self.until, salon=self.salon)
        rows = export_tender_totals(
            self.since, self.until, salon=self.salon)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["salon_id"], self.salon.pk)
            self.assertEqual(
                Decimal(row["amount"]), totals.by_method[row["method"]])
            self.assertEqual(Decimal(row["total"]), totals.total)
            self.assertEqual(row["count"], totals.count)
        self.assertEqual(totals.total, Decimal("85.00"))
        self.assertEqual(totals.count, 1)
        parsed = _rows(export_tender_totals_csv(
            self.since, self.until, salon=self.salon))
        self.assertEqual(
            [int(r["salon_id"]) for r in parsed],
            [self.salon.pk] * len(parsed))

    def test_empty_range_zero_filled_rows(self):
        totals = tender_totals(self.since, self.until)
        rows = export_tender_totals(self.since, self.until)
        self.assertEqual(
            [r["method"] for r in rows], list(totals.by_method))
        self.assertEqual([r["amount"] for r in rows], ["0.00", "0.00"])
        self.assertEqual([r["total"] for r in rows], ["0.00", "0.00"])
        self.assertEqual([r["count"] for r in rows], [0, 0])
        parsed = _rows(export_tender_totals_csv(self.since, self.until))
        self.assertEqual([r["amount"] for r in parsed], ["0.00", "0.00"])
        self.assertEqual([r["count"] for r in parsed], ["0", "0"])

    def test_read_only_records_unchanged(self):
        self._pay(self.salon, "cash", "85.00")
        before = (
            Payment.objects.count(), Sale.objects.count(),
            SaleItem.objects.count(), Cashup.objects.count(),
        )
        export_tender_totals(self.since, self.until, salon=self.salon)
        export_tender_totals_csv(self.since, self.until, salon=self.salon)
        after = (
            Payment.objects.count(), Sale.objects.count(),
            SaleItem.objects.count(), Cashup.objects.count(),
        )
        self.assertEqual(after, before)
