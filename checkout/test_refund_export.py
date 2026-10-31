import csv
import datetime
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Refund, Sale
from checkout.refund_export import (
    EXPORT_FIELDNAMES,
    export_refunds,
    export_refunds_csv,
    refund_export_row,
)
from saloncore.models import Salon


class RefundExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)

    def _at(self, day, hour=12, minute=0):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, minute)),
            datetime.timezone.utc,
        )

    def _refund(self, day=None, hour=12, minute=0, amount="20.00",
                reason="Changed mind", tender=Payment.Method.CASH,
                salon=None):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED,
            completed_at=self._at(day or self.day),
        )
        refund = Refund.objects.create(
            sale=sale, amount=Decimal(amount), reason=reason, tender=tender,
        )
        Refund.objects.filter(pk=refund.pk).update(
            created_at=self._at(day or self.day, hour=hour, minute=minute)
        )
        refund.refresh_from_db()
        return refund

    def test_row_shape_fields_as_stored_and_csv_agrees(self):
        refund = self._refund(amount="20.5", reason="Late, sorry",
                              tender=Payment.Method.EXTERNAL)
        rows = export_refunds(self.salon, self.day, self.day)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(list(row), EXPORT_FIELDNAMES)
        self.assertEqual(row["id"], refund.pk)
        self.assertEqual(row["refund_id"], refund.pk)
        self.assertEqual(row["salon_id"], self.salon.pk)
        self.assertEqual(row["sale_id"], refund.sale_id)
        self.assertEqual(row["created_at"], refund.created_at.isoformat())
        self.assertEqual(row["amount"], "20.50")
        self.assertEqual(row["reason"], "Late, sorry")
        self.assertEqual(row["tender"], "external")
        self.assertEqual(refund_export_row(refund), row)
        parsed = list(csv.DictReader(io.StringIO(
            export_refunds_csv(self.salon, self.day, self.day))))
        self.assertEqual(len(parsed), 1)
        for key in EXPORT_FIELDNAMES:
            self.assertEqual(parsed[0][key], str(row[key]))

    def test_rows_in_range_only_and_chronological(self):
        before = self._refund(day=self.day - datetime.timedelta(days=1))
        first = self._refund()
        second = self._refund(day=self.day + datetime.timedelta(days=1))
        after = self._refund(day=self.day + datetime.timedelta(days=2))
        rows = export_refunds(
            self.salon, self.day, self.day + datetime.timedelta(days=1))
        self.assertEqual([r["id"] for r in rows], [first.pk, second.pk])
        self.assertNotIn(before.pk, [r["id"] for r in rows])
        self.assertNotIn(after.pk, [r["id"] for r in rows])

    def test_other_salon_excluded(self):
        own = self._refund()
        self._refund(salon=self.other)
        rows = export_refunds(self.salon, self.day, self.day)
        self.assertEqual([r["id"] for r in rows], [own.pk])
        csv_text = export_refunds_csv(self.salon, self.day)
        self.assertEqual(len(csv_text.strip().splitlines()), 2)

    def test_range_boundaries_are_inclusive_local_days(self):
        start = self._refund(hour=0, minute=0)
        end = self._refund(day=self.day + datetime.timedelta(days=1),
                           hour=23, minute=59)
        self._refund(day=self.day - datetime.timedelta(days=1),
                     hour=23, minute=59)
        self._refund(day=self.day + datetime.timedelta(days=2),
                     hour=0, minute=0)
        rows = export_refunds(
            self.salon, self.day, self.day + datetime.timedelta(days=1))
        self.assertEqual([r["id"] for r in rows], [start.pk, end.pk])
        # Single-day default: date_to omitted means date_from only.
        self.assertEqual(
            [r["id"] for r in export_refunds(self.salon, self.day)],
            [start.pk])

    def test_empty_range_is_empty_list_and_header_only_csv(self):
        self._refund()
        empty_from = self.day + datetime.timedelta(days=10)
        empty_to = self.day + datetime.timedelta(days=11)
        self.assertEqual(export_refunds(self.salon, empty_from, empty_to), [])
        self.assertEqual(
            export_refunds_csv(self.salon, empty_from, empty_to),
            ",".join(EXPORT_FIELDNAMES) + "\n")
        # A reversed range is empty too, never an error or None.
        self.assertEqual(export_refunds(self.salon, empty_to, empty_from), [])
        self.assertEqual(
            export_refunds_csv(self.salon, empty_to, empty_from),
            ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_amounts_formatted_to_two_decimal_places(self):
        self._refund(amount="5")
        self._refund(amount="7.5")
        self._refund(amount="9.99")
        amounts = [r["amount"] for r in export_refunds(self.salon, self.day)]
        self.assertEqual(amounts, ["5.00", "7.50", "9.99"])

    def test_export_is_read_only(self):
        refund = self._refund()
        export_refunds(self.salon, self.day, self.day)
        export_refunds_csv(self.salon, self.day, self.day)
        self.assertEqual(Refund.objects.count(), 1)
        self.assertEqual(Sale.objects.count(), 1)
        refund.refresh_from_db()
        self.assertEqual(refund.amount, Decimal("20.00"))
        self.assertEqual(refund.reason, "Changed mind")
        self.assertEqual(refund.tender, Payment.Method.CASH)
