import csv
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Sale, SaleItem
from checkout.tender_mix import tender_mix
from checkout.tender_mix_export import (
    EXPORT_FIELDNAMES, export_tender_mix, export_tender_mix_csv,
    tender_mix_csv,
)
from saloncore.models import Salon


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class TenderMixExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        now = timezone.now()
        self.since = now - timezone.timedelta(hours=1)
        self.until = now + timezone.timedelta(hours=1)

    def _pay(self, salon, method, amount, status="completed"):
        sale = Sale.objects.create(
            salon=salon, status="completed", completed_at=timezone.now())
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal(amount))
        return Payment.objects.create(
            sale=sale, method=method, amount=Decimal(amount), status=status)

    def test_header_and_row_keys(self):
        text = export_tender_mix_csv(self.salon, self.since, self.until)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        rows = export_tender_mix(self.salon, self.since, self.until)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(list(row), EXPORT_FIELDNAMES)

    def test_rows_match_service_output(self):
        self._pay(self.salon, "cash", "100.00")
        self._pay(self.salon, "external", "50.00")
        self._pay(self.other, "cash", "999.00")
        mix = tender_mix(self.salon, self.since, self.until)
        rows = export_tender_mix(self.salon, self.since, self.until)
        expected = [
            {
                "salon_id": self.salon.pk,
                "start": self.since.isoformat(),
                "end": self.until.isoformat(),
                "method": entry.method,
                "amount": str(entry.total.quantize(Decimal("0.01"))),
                "total": str(mix.total.quantize(Decimal("0.01"))),
                "share_percent": str(
                    entry.share_percent.quantize(Decimal("0.01"))),
                "count": mix.count,
            }
            for entry in mix.entries
        ]
        self.assertEqual(rows, expected)
        self.assertEqual(rows[0]["share_percent"], "66.67")
        self.assertEqual(rows[1]["share_percent"], "33.33")
        self.assertEqual(
            sum(Decimal(r["amount"]) for r in rows), mix.total)

    def test_csv_agrees_with_list_and_alias(self):
        self._pay(self.salon, "cash", "85.00")
        text = export_tender_mix_csv(self.salon, self.since, self.until)
        parsed = [
            {**r, "salon_id": int(r["salon_id"]), "count": int(r["count"])}
            for r in _rows(text)
        ]
        self.assertEqual(
            parsed, export_tender_mix(self.salon, self.since, self.until))
        self.assertEqual(
            tender_mix_csv(self.salon, self.since, self.until), text)

    def test_empty_window_zero_rows_empty_shares(self):
        rows = export_tender_mix(self.salon, self.since, self.until)
        self.assertEqual([r["amount"] for r in rows], ["0.00", "0.00"])
        self.assertEqual([r["total"] for r in rows], ["0.00", "0.00"])
        self.assertEqual([r["share_percent"] for r in rows], ["", ""])
        self.assertEqual([r["count"] for r in rows], [0, 0])
        parsed = _rows(
            export_tender_mix_csv(self.salon, self.since, self.until))
        self.assertEqual([r["share_percent"] for r in parsed], ["", ""])

    def test_reversed_window_raises(self):
        with self.assertRaises(ValueError):
            export_tender_mix(self.salon, self.until, self.since)
        with self.assertRaises(ValueError):
            export_tender_mix_csv(self.salon, self.until, self.since)

    def test_read_only_records_unchanged(self):
        self._pay(self.salon, "cash", "85.00")
        before = (Payment.objects.count(), Sale.objects.count())
        export_tender_mix(self.salon, self.since, self.until)
        export_tender_mix_csv(self.salon, self.since, self.until)
        self.assertEqual(
            (Payment.objects.count(), Sale.objects.count()), before)
