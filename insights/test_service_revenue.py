import csv
import datetime
import io
import os
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.service_revenue import ServiceRevenue, revenue_by_service
from insights.service_revenue_export import (
    SERVICE_REVENUE_FIELDNAMES,
    export_service_revenue_csv,
)
from saloncore.models import Salon, Service, ServiceCategory

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


class RevenueByServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        other_cat = ServiceCategory.objects.create(salon=self.other, name="Hair")
        # 45 + 15 processing = 60 total minutes.
        self.cut = Service.objects.create(category=cat, name="Haircut", service_minutes=45, processing_minutes=15)
        self.colour = Service.objects.create(category=cat, name="Colour", service_minutes=30)
        self.free = Service.objects.create(category=cat, name="Consult", service_minutes=0)
        self.other_cut = Service.objects.create(category=other_cat, name="Haircut", service_minutes=45)

    def _sale(self, *, salon=None, day_offset=0,
              status=Sale.Status.COMPLETED, completed=True):
        sale = Sale.objects.create(salon=salon or self.salon, status=status)
        stamp = datetime.datetime(2026, 11, 2 + day_offset, 12, 0, tzinfo=UTC)
        updates = {"created_at": stamp}
        if completed:
            updates["completed_at"] = stamp
        Sale.objects.filter(pk=sale.pk).update(**updates)
        sale.refresh_from_db()
        return sale

    def _item(self, sale, price, *, kind=SaleItem.Kind.SERVICE,
              quantity=1, service=None, description=""):
        return SaleItem.objects.create(sale=sale, kind=kind, quantity=quantity, unit_price=Decimal(price), service=service, description=description)

    def test_revenue_grouped_ranked_and_revenue_per_hour(self):
        sale = self._sale()
        self._item(sale, "85.00", service=self.cut)
        sale2 = self._sale(day_offset=1)
        self._item(sale2, "85.00", service=self.cut)
        self._item(sale2, "60.00", service=self.colour, quantity=2)
        rows = revenue_by_service(self.salon, START, END)
        self.assertTrue(all(isinstance(r, ServiceRevenue) for r in rows))
        self.assertEqual([r.service_name for r in rows],
                         ["Haircut", "Colour"])
        cut, colour = rows
        self.assertEqual(cut.service, self.cut)
        self.assertEqual(cut.revenue, Decimal("170.00"))
        self.assertIsInstance(cut.revenue, Decimal)
        self.assertEqual((cut.quantity, cut.line_count, cut.sale_count),
                         (2, 2, 2))
        self.assertEqual(cut.duration_minutes, 60)
        self.assertEqual(cut.total_duration_minutes, 120)
        self.assertEqual(cut.revenue_per_hour, Decimal("85.00"))  # 170 / 2h
        self.assertIsInstance(cut.revenue_per_hour, Decimal)
        self.assertEqual(colour.revenue_per_hour, Decimal("120.00"))  # 120 / 1h

    def test_zero_and_unknown_duration_give_none_per_hour(self):
        sale = self._sale()
        self._item(sale, "0.00", service=self.free)
        self._item(sale, "40.00", description="Mystery service")
        self._item(sale, "10.00")
        rows = {r.service_name: r for r in revenue_by_service(self.salon, START, END)}
        self.assertIsNone(rows["Consult"].revenue_per_hour)
        self.assertIsNone(rows["Consult"].total_duration_minutes)
        self.assertIsNone(rows["Mystery service"].revenue_per_hour)
        self.assertIsNone(rows["Mystery service"].service)
        self.assertEqual(rows["Unknown service"].revenue, Decimal("10.00"))

    def test_completed_only_product_excluded_and_salon_scoped(self):
        for status in (Sale.Status.VOIDED, Sale.Status.OPEN):
            sale = self._sale(status=status)
            self._item(sale, "999.00", service=self.cut)
        sale = self._sale()
        self._item(sale, "999.00", kind=SaleItem.Kind.PRODUCT)
        other_sale = self._sale(salon=self.other)
        self._item(other_sale, "999.00", service=self.other_cut)
        self.assertEqual(revenue_by_service(self.salon, START, END), [])

    def test_window_inclusive_created_fallback_and_reversed(self):
        for offset, price in ((0, "10.00"), (6, "20.00"),
                              (-1, "999.00"), (7, "999.00")):
            sale = self._sale(day_offset=offset, completed=False)
            self._item(sale, price, service=self.cut)
        rows = revenue_by_service(self.salon, START, END)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].revenue, Decimal("30.00"))
        self.assertEqual(revenue_by_service(self.salon, END, START), [])
        self.assertEqual(revenue_by_service(self.salon, START + timedelta(days=30), END + timedelta(days=30)), [])

    def test_same_name_services_never_merge(self):
        twin = Service.objects.create(category=self.cut.category, name="Haircut", service_minutes=45)
        sale = self._sale()
        self._item(sale, "10.00", service=self.cut)
        self._item(sale, "20.00", service=twin)
        rows = revenue_by_service(self.salon, START, END)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r.service_id for r in rows},
                         {self.cut.pk, twin.pk})


class ServiceRevenueExportAndCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.cut = Service.objects.create(category=cat, name="Haircut", service_minutes=60)
        sale = Sale.objects.create(salon=self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(sale=sale, kind=SaleItem.Kind.SERVICE, service=self.cut, quantity=1, unit_price=Decimal("90.00"))
        SaleItem.objects.create(sale=sale, kind=SaleItem.Kind.SERVICE, description="Mystery", quantity=1, unit_price=Decimal("30.00"))

    def test_csv_header_rows_and_empty_per_hour(self):
        text = export_service_revenue_csv(self.salon, START, END)
        parsed = list(csv.reader(io.StringIO(text)))
        self.assertEqual(parsed[0], SERVICE_REVENUE_FIELDNAMES)
        self.assertEqual(parsed[1][1:], ["Haircut", "90.00", "1", "1",
                                         "1", "60", "60", "90.00"])
        self.assertEqual(parsed[2][1], "Mystery")
        self.assertEqual(parsed[2][-1], "")  # unknown duration -> empty
        self.assertTrue(text.endswith("\n"))

    def test_csv_empty_window_is_header_only(self):
        text = export_service_revenue_csv(
            self.salon, date(2027, 1, 1), date(2027, 1, 7))
        self.assertEqual(text.splitlines(),
                         [",".join(SERVICE_REVENUE_FIELDNAMES)])

    def test_command_stdout_and_file_match_service(self):
        out = io.StringIO()
        call_command("export_service_revenue", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        self.assertEqual(out.getvalue(), export_service_revenue_csv(
            self.salon, START, END))
        # Real filesystem writes are blocked in this test
        # environment, so the --output branch is verified through
        # a mocked open: the command must write exactly the
        # service CSV to the given path and nothing to stdout.
        from unittest import mock
        mocked = mock.mock_open()
        with mock.patch(
                "insights.management.commands.export_service_revenue"
                ".open", mocked, create=True):
            file_out = io.StringIO()
            call_command("export_service_revenue",
                         salon_id=self.salon.pk, start_date=START,
                         end_date=END, output="svc.csv",
                         stdout=file_out)
        mocked.assert_called_once_with(
            "svc.csv", "w", encoding="utf-8", newline="")
        handle = mocked()
        handle.write.assert_called_once_with(out.getvalue())
        self.assertEqual(file_out.getvalue(), "")

    def test_command_errors(self):
        with self.assertRaises(CommandError):
            call_command("export_service_revenue",
                         salon_id=self.salon.pk + 999,
                         start_date=START, end_date=END,
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_service_revenue",
                         salon_id=self.salon.pk, start_date="bad",
                         end_date=END, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_service_revenue",
                         salon_id=self.salon.pk, stdout=io.StringIO())
