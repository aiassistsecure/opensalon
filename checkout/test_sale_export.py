"""Sale verbatim export: stored rows, every concrete field."""
import csv
import datetime
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Payment, Sale
from checkout.sale_export import (
    EXPORT_FIELDNAMES,
    SALE_EXPORT_FIELDNAMES,
    export_sales,
    export_sales_csv,
    sale_export_row,
    sales_csv,
)
from clients.models import Client
from saloncore.models import Salon


class SaleExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Sale Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Ada", last_name="Optin")

    def _at(self, day, hour=12):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, 0)),
            datetime.timezone.utc)

    def _sale(self, salon=None, day=None, **kwargs):
        kwargs.setdefault("status", Sale.Status.COMPLETED)
        sale = Sale.objects.create(salon=salon or self.salon, **kwargs)
        if day is not None:
            Sale.objects.filter(pk=sale.pk).update(
                created_at=self._at(day))
            sale.refresh_from_db()
        return sale

    def _sales(self):
        completed = self._sale(
            client=self.client, discount_amount=Decimal("10.00"),
            completed_at=self._at(self.day, 13))
        walkin = self._sale()
        voided = self._sale(
            status=Sale.Status.VOIDED,
            voided_at=self._at(self.day, 14),
            void_reason="Entered in error, duplicate")
        return [completed, walkin, voided]

    def test_fieldnames_guard_against_concrete_fields(self):
        expected = [
            field.attname for field in Sale._meta.concrete_fields
        ]
        self.assertEqual(SALE_EXPORT_FIELDNAMES, expected)
        self.assertEqual(EXPORT_FIELDNAMES, SALE_EXPORT_FIELDNAMES)
        self.assertNotIn("provider_reference", SALE_EXPORT_FIELDNAMES)
        self.assertIs(sales_csv, export_sales_csv)

    def test_rows_verbatim_every_field(self):
        sales = self._sales()
        records = export_sales(self.salon)
        self.assertEqual([r["id"] for r in records],
                         [sale.pk for sale in sales])
        for record in records:
            self.assertEqual(list(record.keys()),
                             SALE_EXPORT_FIELDNAMES)
        self.assertEqual(records[0], {
            "id": sales[0].pk, "salon_id": self.salon.pk,
            "client_id": self.client.pk, "status": "completed",
            "discount_amount": "10.00",
            "created_at": sales[0].created_at.isoformat(),
            "completed_at": sales[0].completed_at.isoformat(),
            "voided_at": None, "void_reason": ""})
        self.assertIsNone(records[1]["client_id"])
        self.assertEqual(records[1]["discount_amount"], "0.00")
        self.assertIsNone(records[1]["completed_at"])
        self.assertEqual(records[2]["status"], "voided")
        self.assertEqual(records[2]["voided_at"],
                         sales[2].voided_at.isoformat())
        self.assertEqual(records[2]["void_reason"],
                         "Entered in error, duplicate")
        self.assertEqual(sale_export_row(sales[0]), records[0])

    def test_csv_agrees_with_dict_export(self):
        self._sales()
        text = export_sales_csv(self.salon)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], SALE_EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        records = export_sales(self.salon)
        self.assertEqual(len(parsed), len(records))
        for parsed_row, record in zip(parsed, records):
            for key in SALE_EXPORT_FIELDNAMES:
                exp = "" if record[key] is None else str(record[key])
                self.assertEqual(parsed_row[key], exp)
        self.assertEqual(parsed[2]["void_reason"],
                         "Entered in error, duplicate")

    def test_salon_scoping_empty_and_none(self):
        self._sales()
        self._sale(salon=self.other)
        self.assertEqual(len(export_sales(self.salon)), 3)
        self.assertEqual(len(export_sales(self.other)), 1)
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        self.assertEqual(export_sales(empty), [])
        self.assertEqual(
            export_sales_csv(empty),
            ",".join(SALE_EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(export_sales(None), [])
        self.assertEqual(
            export_sales_csv(None),
            ",".join(SALE_EXPORT_FIELDNAMES) + "\n")

    def test_no_provider_reference_anywhere(self):
        sale = self._sale()
        Payment.objects.create(
            sale=sale, method=Payment.Method.CASH,
            amount=Decimal("85.00"), status=Payment.Status.COMPLETED,
            provider_reference="PROV-SECRET-1")
        text = export_sales_csv(self.salon)
        self.assertNotIn("provider_reference", text)
        self.assertNotIn("PROV-SECRET-1", text)
        for record in export_sales(self.salon):
            self.assertNotIn("provider_reference", record)

    def test_date_range_filters_on_created_at(self):
        in_range = self._sale(day=self.day)
        self._sale(day=self.day - datetime.timedelta(days=1))
        next_day = self._sale(day=self.day + datetime.timedelta(days=1))
        rows = export_sales(self.salon, self.day, self.day)
        self.assertEqual([r["id"] for r in rows], [in_range.pk])
        rows = export_sales(
            self.salon, self.day, self.day + datetime.timedelta(days=1))
        self.assertEqual([r["id"] for r in rows],
                         [in_range.pk, next_day.pk])
        # Single-day default when date_to is omitted.
        self.assertEqual(
            [r["id"] for r in export_sales(self.salon, self.day)],
            [in_range.pk])

    def test_reversed_range_and_read_only(self):
        sale = self._sale(day=self.day, discount_amount=Decimal("3.00"))
        later = self.day + datetime.timedelta(days=1)
        self.assertEqual(export_sales(self.salon, later, self.day), [])
        self.assertEqual(
            export_sales_csv(self.salon, later, self.day),
            ",".join(SALE_EXPORT_FIELDNAMES) + "\n")
        export_sales(self.salon)
        export_sales_csv(self.salon)
        self.assertEqual(Sale.objects.count(), 1)
        sale.refresh_from_db()
        self.assertEqual(sale.discount_amount, Decimal("3.00"))
