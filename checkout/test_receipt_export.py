import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Receipt, Sale, SaleItem
from checkout.receipt_export import (
    EXPORT_FIELDNAMES,
    export_receipts,
    receipt_export_row,
)
from checkout.receipts import build_receipt
from clients.models import Client
from saloncore.models import Salon


def _aware(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour))
    )


class ReceiptExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example",
            email="client@example.com",
        )
        self.day = datetime.date(2026, 10, 3)

    def _receipt(self, issued_day, total="85.00", client="default",
                 salon=None, sent=False):
        sale = Sale.objects.create(
            salon=salon or self.salon,
            client=self.client if client == "default" else client,
            status=Sale.Status.COMPLETED,
            completed_at=_aware(issued_day),
        )
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal(total),
        )
        receipt = build_receipt(sale)
        updates = {"issued_at": _aware(issued_day)}
        if sent:
            updates["recipient_email"] = "client@example.com"
            updates["sent_at"] = _aware(issued_day, hour=13)
        Receipt.objects.filter(pk=receipt.pk).update(**updates)
        receipt.refresh_from_db()
        return receipt

    def test_row_shape_and_delivery_fields_as_stored(self):
        sent = self._receipt(self.day, sent=True)
        walk_in = self._receipt(self.day, client=None)
        rows = {r["id"]: r for r in export_receipts(self.day, self.day)}
        self.assertEqual(list(rows[sent.pk]), EXPORT_FIELDNAMES)
        row = rows[sent.pk]
        self.assertEqual(row["receipt_id"], sent.pk)
        self.assertEqual(row["sale_id"], sent.sale_id)
        self.assertEqual(row["salon_id"], self.salon.pk)
        self.assertEqual(row["client_id"], self.client.pk)
        self.assertEqual(row["total"], "85.00")
        self.assertEqual(row["issued_at"], sent.issued_at.isoformat())
        self.assertEqual(row["delivery_channel"], "email")
        self.assertEqual(row["delivery_status"], "sent")
        self.assertEqual(row["recipient_email"], "client@example.com")
        self.assertEqual(row["sent_at"], sent.sent_at.isoformat())
        unsent = rows[walk_in.pk]
        self.assertIsNone(unsent["client_id"])
        self.assertIsNone(unsent["delivery_channel"])
        self.assertEqual(unsent["delivery_status"], "not_sent")
        self.assertEqual(unsent["recipient_email"], "")
        self.assertIsNone(unsent["sent_at"])
        self.assertEqual(receipt_export_row(sent), row)

    def test_range_filtering_inclusive_whole_days(self):
        before = self._receipt(self.day - datetime.timedelta(days=1))
        first = self._receipt(self.day)
        last = self._receipt(self.day + datetime.timedelta(days=1))
        after = self._receipt(self.day + datetime.timedelta(days=2))
        ids = [r["id"] for r in export_receipts(
            self.day, self.day + datetime.timedelta(days=1)
        )]
        self.assertEqual(ids, [first.pk, last.pk])
        self.assertNotIn(before.pk, ids)
        self.assertNotIn(after.pk, ids)

    def test_ordering_is_chronological_oldest_first(self):
        later = self._receipt(self.day + datetime.timedelta(days=1))
        earlier = self._receipt(self.day)
        middle = self._receipt(self.day, total="24.00")
        # Same instant as `earlier`: the id tiebreak is deterministic.
        ids = [r["id"] for r in export_receipts()]
        self.assertEqual(ids, [earlier.pk, middle.pk, later.pk])

    def test_empty_range_is_empty_list(self):
        self._receipt(self.day)
        self.assertEqual(
            export_receipts(
                self.day + datetime.timedelta(days=10),
                self.day + datetime.timedelta(days=11),
            ),
            [],
        )

    def test_salon_scope_excludes_other_salons(self):
        own = self._receipt(self.day)
        other_salon = Salon.objects.create(name="Other Salon")
        self._receipt(self.day, salon=other_salon, client=None)
        rows = export_receipts(self.day, self.day, salon=self.salon)
        self.assertEqual([r["id"] for r in rows], [own.pk])

    def test_datetime_window_and_reversed_range(self):
        receipt = self._receipt(self.day)
        start = _aware(self.day, hour=0)
        end = _aware(self.day, hour=23)
        self.assertEqual(
            [r["id"] for r in export_receipts(start, end)], [receipt.pk]
        )
        with self.assertRaises(ValueError):
            export_receipts(
                self.day + datetime.timedelta(days=1), self.day
            )

    def test_export_is_read_only(self):
        self._receipt(self.day, sent=True)
        before = Receipt.objects.count()
        export_receipts()
        self.assertEqual(Receipt.objects.count(), before)
        receipt = Receipt.objects.get()
        self.assertIsNotNone(receipt.sent_at)
