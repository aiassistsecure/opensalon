"""Per-client filter tests for the receipt export service."""
import csv
import datetime
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Receipt, Sale, SaleItem
from checkout.receipt_export import (
    EXPORT_FIELDNAMES,
    export_receipts,
    export_receipts_csv,
)
from checkout.receipts import build_receipt
from clients.models import Client
from saloncore.models import Salon


def _aware(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour)))


class ReceiptExportClientFilterTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example",
            email="client@example.com")
        self.other_client = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person")
        self.day = datetime.date(2026, 10, 3)

    def _receipt(self, client="default", salon=None, sent=False):
        sale = Sale.objects.create(
            salon=salon or self.salon,
            client=self.client if client == "default" else client,
            status=Sale.Status.COMPLETED,
            completed_at=_aware(self.day))
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal("85.00"))
        receipt = build_receipt(sale)
        updates = {"issued_at": _aware(self.day)}
        if sent:
            updates["recipient_email"] = "client@example.com"
            updates["sent_at"] = _aware(self.day, hour=13)
        Receipt.objects.filter(pk=receipt.pk).update(**updates)
        receipt.refresh_from_db()
        return receipt

    def test_client_instance_filters_to_that_client(self):
        first = self._receipt()
        self._receipt(client=self.other_client)
        self._receipt(client=None)
        rows = export_receipts(self.day, self.day, salon=self.salon,
                               client=self.client)
        self.assertEqual([r["id"] for r in rows], [first.pk])
        self.assertEqual(rows[0]["client_id"], self.client.pk)

    def test_client_id_filters_to_that_client(self):
        self._receipt()
        second = self._receipt(client=self.other_client)
        rows = export_receipts(self.day, self.day, salon=self.salon,
                               client=self.other_client.pk)
        self.assertEqual([r["id"] for r in rows], [second.pk])
        self.assertEqual(rows[0]["client_id"], self.other_client.pk)

    def test_unfiltered_unchanged(self):
        self._receipt()
        self._receipt(client=None)
        default = export_receipts(self.day, self.day, salon=self.salon)
        self.assertEqual(len(default), 2)
        self.assertEqual(
            export_receipts(self.day, self.day, salon=self.salon,
                            client=None), default)
        self.assertEqual(
            export_receipts_csv(self.day, self.day, salon=self.salon,
                                client=None),
            export_receipts_csv(self.day, self.day, salon=self.salon))

    def test_csv_and_list_agree(self):
        first = self._receipt()
        self._receipt(client=self.other_client)
        rows = export_receipts(self.day, self.day, salon=self.salon,
                               client=self.client)
        parsed = list(csv.DictReader(io.StringIO(export_receipts_csv(
            self.day, self.day, salon=self.salon, client=self.client))))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["id"], str(first.pk))
        for key in EXPORT_FIELDNAMES:
            expected = "" if rows[0][key] is None else str(rows[0][key])
            self.assertEqual(parsed[0][key], expected)

    def test_client_without_receipts_is_empty_and_header_only_csv(self):
        self._receipt()
        empty_client = Client.objects.create(
            salon=self.salon, first_name="No", last_name="Receipts")
        self.assertEqual(
            export_receipts(self.day, self.day, salon=self.salon,
                            client=empty_client), [])
        self.assertEqual(
            export_receipts_csv(self.day, self.day, salon=self.salon,
                                client=empty_client.pk),
            ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_unknown_client_id_raises_value_error(self):
        self._receipt()
        with self.assertRaises(ValueError):
            export_receipts(self.day, self.day, salon=self.salon,
                            client=999999)
        with self.assertRaises(ValueError):
            export_receipts_csv(self.day, self.day, salon=self.salon,
                                client=999999)

    def test_unsaved_client_instance_raises_value_error(self):
        unsaved = Client(salon=self.salon, first_name="A", last_name="B")
        with self.assertRaises(ValueError):
            export_receipts(self.day, self.day, salon=self.salon,
                            client=unsaved)

    def test_other_salon_client_raises_value_error(self):
        self._receipt()
        theirs = Client.objects.create(
            salon=self.other, first_name="Their", last_name="Client")
        their_receipt = self._receipt(client=theirs, salon=self.other)
        with self.assertRaises(ValueError):
            export_receipts(self.day, self.day, salon=self.salon,
                            client=theirs)
        with self.assertRaises(ValueError):
            export_receipts(self.day, self.day, salon=self.salon,
                            client=theirs.pk)
        with self.assertRaises(ValueError):
            export_receipts_csv(self.day, self.day, salon=self.salon,
                                client=theirs)
        # The same client resolves fine in its own salon.
        self.assertEqual(
            [r["id"] for r in export_receipts(
                self.day, self.day, salon=self.other, client=theirs)],
            [their_receipt.pk])

    def test_client_filter_composes_with_sale_delivery_and_window(self):
        sent = self._receipt(sent=True)
        self._receipt()
        self._receipt(client=self.other_client, sent=True)
        rows = export_receipts(self.day, self.day, salon=self.salon,
                               client=self.client, delivery_status="sent")
        self.assertEqual([r["id"] for r in rows], [sent.pk])
        rows = export_receipts(self.day, self.day, salon=self.salon,
                               sale=sent.sale, client=self.client)
        self.assertEqual([r["id"] for r in rows], [sent.pk])
        # A sale belonging to another client composes to nothing.
        self.assertEqual(
            export_receipts(self.day, self.day, salon=self.salon,
                            sale=sent.sale, client=self.other_client), [])
        other_day = self.day + datetime.timedelta(days=5)
        self.assertEqual(
            export_receipts(other_day, other_day, salon=self.salon,
                            client=self.client), [])

    def test_client_is_keyword_only(self):
        self._receipt()
        with self.assertRaises(TypeError):
            export_receipts(self.day, self.day, self.salon, None,
                            "sent", self.client)
