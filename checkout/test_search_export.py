import csv
import datetime
import io
import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale, SaleItem
from checkout.search import search_sales
from checkout.search_export import (
    EXPORT_FIELDNAMES,
    export_search_rows,
    export_search_sales,
    export_search_sales_csv,
    search_export_row,
    search_sales_csv,
)
from clients.models import Client
from saloncore.models import Salon


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class SearchExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.ana = Client.objects.create(
            salon=self.salon, first_name="Ana", last_name="Lopez"
        )
        self.day = datetime.date(2026, 10, 3)

    def _at(self, day, hour=12):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, 0)),
            datetime.timezone.utc,
        )

    def _sale(self, salon=None, client=None, price="85.00", qty=1,
              status=Sale.Status.COMPLETED, day=None, completed=True):
        sale = Sale.objects.create(
            salon=salon or self.salon, client=client, status=status
        )
        SaleItem.objects.create(
            sale=sale, kind="service", description="service",
            unit_price=Decimal(price), quantity=qty,
        )
        stamp = self._at(day or self.day)
        updates = {"created_at": stamp}
        if completed:
            updates["completed_at"] = stamp
        Sale.objects.filter(pk=sale.pk).update(**updates)
        sale.refresh_from_db()
        return sale

    def test_header_row_keys_and_values(self):
        sale = self._sale(client=self.ana, price="85.5")
        self.assertEqual(
            EXPORT_FIELDNAMES,
            ["id", "sale_id", "salon_id", "client_id", "status",
             "created_at", "completed_at", "total"],
        )
        rows = export_search_sales(self.salon)
        self.assertEqual(rows, [{
            "id": sale.pk, "sale_id": sale.pk,
            "salon_id": self.salon.pk, "client_id": self.ana.pk,
            "status": "completed",
            "created_at": sale.created_at.isoformat(),
            "completed_at": sale.completed_at.isoformat(),
            "total": "85.50",
        }])
        self.assertEqual(list(rows[0]), EXPORT_FIELDNAMES)
        json.dumps(rows)  # JSON-serializable, money as strings
        self.assertIsInstance(rows[0]["total"], str)
        text = export_search_sales_csv(self.salon)
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))
        self.assertEqual(list(_rows(text)[0]), EXPORT_FIELDNAMES)

    def test_row_builder_uses_search_total(self):
        sale = self._sale(price="20.00", qty=2)
        found = search_sales(self.salon)[0]
        self.assertEqual(search_export_row(found)["total"], "40.00")
        self.assertEqual(search_export_row(sale)["total"], "40.00")

    def test_delegates_to_search_sales_with_same_args(self):
        with mock.patch(
            "checkout.search_export.search_sales",
            wraps=search_sales,
        ) as spy:
            export_search_sales(
                self.salon, client_name="ana", min_total="10.00",
                include_voided=True,
            )
        spy.assert_called_once_with(
            self.salon, client_name="ana", date_from=None,
            date_to=None, min_total="10.00", include_voided=True,
        )

    def test_matches_service_order_and_filters(self):
        older = self._sale(day=self.day - datetime.timedelta(days=1))
        newer = self._sale(client=self.ana, day=self.day)
        self._sale(status=Sale.Status.VOIDED, day=self.day)
        rows = export_search_sales(self.salon)
        self.assertEqual([r["id"] for r in rows], [newer.pk, older.pk])
        self.assertEqual(
            [r["id"] for r in export_search_sales(
                self.salon, client_name="lopez")],
            [newer.pk],
        )
        self.assertEqual(
            [r["id"] for r in export_search_sales(
                self.salon, min_total=Decimal("85.00"))],
            [newer.pk, older.pk],
        )
        self.assertEqual(
            export_search_sales(
                self.salon, date_from=self.day, date_to=self.day)[0]["id"],
            newer.pk,
        )
        voided_rows = export_search_sales(self.salon, include_voided=True)
        self.assertEqual(len(voided_rows), 3)

    def test_csv_agrees_with_list_and_aliases(self):
        self._sale(client=self.ana)
        self._sale()
        text = export_search_sales_csv(self.salon)
        parsed = [{
            **r,
            "id": int(r["id"]), "sale_id": int(r["sale_id"]),
            "salon_id": int(r["salon_id"]),
            "client_id": int(r["client_id"]) if r["client_id"] else None,
            "completed_at": r["completed_at"] or None,
        } for r in _rows(text)]
        self.assertEqual(parsed, export_search_sales(self.salon))
        self.assertEqual(search_sales_csv(self.salon), text)
        self.assertEqual(export_search_rows(self.salon),
                         export_search_sales(self.salon))

    def test_empty_and_salon_isolation(self):
        self._sale(salon=self.other)
        self.assertEqual(export_search_sales(self.salon), [])
        self.assertEqual(
            export_search_sales_csv(self.salon),
            ",".join(EXPORT_FIELDNAMES) + "\n",
        )
        self.assertEqual(
            export_search_sales(self.salon, client_name="zzz"), [])

    def test_walk_in_client_id_is_none(self):
        self._sale()
        self.assertIsNone(export_search_sales(self.salon)[0]["client_id"])

    def test_service_errors_propagate(self):
        with self.assertRaises(ValueError):
            export_search_sales(None)
        with self.assertRaises(ValueError):
            export_search_sales(self.salon, min_total="not-a-number")
        with self.assertRaises(ValueError):
            export_search_sales_csv(
                self.salon, date_from=self.day,
                date_to=self.day - datetime.timedelta(days=1))

    def test_read_only_records_unchanged(self):
        self._sale(client=self.ana)
        before = (Sale.objects.count(), SaleItem.objects.count())
        export_search_sales(self.salon, client_name="ana")
        export_search_sales_csv(self.salon)
        self.assertEqual((Sale.objects.count(), SaleItem.objects.count()),
                         before)
