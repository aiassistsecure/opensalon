import csv
import datetime
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Sale
from checkout.payment_export import (
    EXPORT_FIELDNAMES,
    export_payments,
    export_payments_csv,
    payment_export_row,
)
from saloncore.models import Salon


class PaymentExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)

    def _at(self, day, hour=12, minute=0):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, minute)),
            datetime.timezone.utc,
        )

    def _payment(self, day=None, hour=12, minute=0, amount="85.00",
                 method=Payment.Method.CASH,
                 status=Payment.Status.COMPLETED,
                 provider_reference="", salon=None):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED,
            completed_at=self._at(day or self.day),
        )
        payment = Payment.objects.create(
            sale=sale, method=method, amount=Decimal(amount),
            status=status, provider_reference=provider_reference,
        )
        stamp = self._at(day or self.day, hour=hour, minute=minute)
        Payment.objects.filter(pk=payment.pk).update(
            created_at=stamp, updated_at=stamp
        )
        payment.refresh_from_db()
        return payment

    def test_row_shape_fields_as_stored_and_csv_agrees(self):
        payment = self._payment(
            amount="85.5", method=Payment.Method.EXTERNAL,
            status=Payment.Status.COMPLETED, provider_reference="ref-123",
        )
        rows = export_payments(self.salon, self.day, self.day)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(list(row), EXPORT_FIELDNAMES)
        self.assertEqual(row["id"], payment.pk)
        self.assertEqual(row["payment_id"], payment.pk)
        self.assertEqual(row["salon_id"], self.salon.pk)
        self.assertEqual(row["sale_id"], payment.sale_id)
        self.assertEqual(row["method"], "external")
        self.assertEqual(row["amount"], "85.50")
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["provider_reference"], "ref-123")
        self.assertEqual(row["created_at"], payment.created_at.isoformat())
        self.assertEqual(row["updated_at"], payment.updated_at.isoformat())
        self.assertEqual(payment_export_row(payment), row)
        parsed = list(csv.DictReader(io.StringIO(
            export_payments_csv(self.salon, self.day, self.day))))
        self.assertEqual(len(parsed), 1)
        for key in EXPORT_FIELDNAMES:
            self.assertEqual(parsed[0][key], str(row[key]))

    def test_date_range_filtering_inclusive_whole_days(self):
        before = self._payment(day=self.day - datetime.timedelta(days=1))
        first = self._payment(hour=0, minute=0)
        last = self._payment(
            day=self.day + datetime.timedelta(days=1), hour=23, minute=59
        )
        after = self._payment(day=self.day + datetime.timedelta(days=2))
        rows = export_payments(
            self.salon, self.day, self.day + datetime.timedelta(days=1)
        )
        self.assertEqual([r["id"] for r in rows], [first.pk, last.pk])
        self.assertNotIn(before.pk, [r["id"] for r in rows])
        self.assertNotIn(after.pk, [r["id"] for r in rows])
        # Single-day default: date_to omitted means date_from only.
        self.assertEqual(
            [r["id"] for r in export_payments(self.salon, self.day)],
            [first.pk],
        )

    def test_salon_scoping_excludes_other_salons(self):
        own = self._payment()
        self._payment(salon=self.other)
        rows = export_payments(self.salon, self.day, self.day)
        self.assertEqual([r["id"] for r in rows], [own.pk])
        csv_text = export_payments_csv(self.salon, self.day)
        self.assertEqual(len(csv_text.strip().splitlines()), 2)
        other_rows = export_payments(self.other, self.day, self.day)
        self.assertEqual(len(other_rows), 1)
        self.assertEqual(other_rows[0]["salon_id"], self.other.pk)

    def test_empty_range_is_empty_list_and_header_only_csv(self):
        self._payment()
        empty_from = self.day + datetime.timedelta(days=10)
        empty_to = self.day + datetime.timedelta(days=11)
        self.assertEqual(export_payments(self.salon, empty_from, empty_to), [])
        self.assertEqual(
            export_payments_csv(self.salon, empty_from, empty_to),
            ",".join(EXPORT_FIELDNAMES) + "\n",
        )
        # A reversed range is empty too, never an error or None.
        self.assertEqual(export_payments(self.salon, empty_to, empty_from), [])
        self.assertEqual(
            export_payments_csv(self.salon, empty_to, empty_from),
            ",".join(EXPORT_FIELDNAMES) + "\n",
        )

    def test_ordering_amounts_and_statuses_as_stored(self):
        later = self._payment(
            day=self.day + datetime.timedelta(days=1), amount="7.5",
            status=Payment.Status.PENDING,
        )
        earlier = self._payment(amount="5", status=Payment.Status.REFUNDED)
        rows = export_payments(
            self.salon, self.day, self.day + datetime.timedelta(days=1)
        )
        self.assertEqual([r["id"] for r in rows], [earlier.pk, later.pk])
        self.assertEqual([r["amount"] for r in rows], ["5.00", "7.50"])
        self.assertEqual([r["status"] for r in rows], ["refunded", "pending"])
        self.assertEqual([r["method"] for r in rows], ["cash", "cash"])

    def test_export_is_read_only(self):
        payment = self._payment(provider_reference="ref-9")
        export_payments(self.salon, self.day, self.day)
        export_payments_csv(self.salon, self.day, self.day)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(Sale.objects.count(), 1)
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("85.00"))
        self.assertEqual(payment.method, Payment.Method.CASH)
        self.assertEqual(payment.provider_reference, "ref-9")
