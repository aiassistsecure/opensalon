import csv
import datetime
import io
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from checkout.models import Sale, SaleItem
from insights.category_mix import CategoryMix, category_mix
from insights.category_mix_export import CATEGORY_MIX_FIELDNAMES, export_category_mix_csv
from saloncore.models import Salon, Service, ServiceCategory

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


class CategoryMixTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.hair = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.nails = ServiceCategory.objects.create(salon=self.salon, name="Nails")
        other_cat = ServiceCategory.objects.create(salon=self.other, name="Hair")
        self.cut = Service.objects.create(category=self.hair, name="Cut", service_minutes=45)
        self.colour = Service.objects.create(category=self.hair, name="Colour", service_minutes=30)
        self.mani = Service.objects.create(category=self.nails, name="Manicure", service_minutes=30)
        self.other_cut = Service.objects.create(category=other_cat, name="Cut", service_minutes=45)

    def _sale(self, *, salon=None, day_offset=0, status=Sale.Status.COMPLETED, completed=True):
        sale = Sale.objects.create(salon=salon or self.salon, status=status)
        stamp = datetime.datetime(2026, 11, 2 + day_offset, 12, 0, tzinfo=UTC)
        updates = {"created_at": stamp}
        if completed:
            updates["completed_at"] = stamp
        Sale.objects.filter(pk=sale.pk).update(**updates)
        sale.refresh_from_db()
        return sale

    def _item(self, sale, price, *, kind=SaleItem.Kind.SERVICE, quantity=1, service=None, description=""):
        return SaleItem.objects.create(sale=sale, kind=kind, quantity=quantity, unit_price=Decimal(price), service=service, description=description)

    def test_grouped_ranked_with_shares(self):
        sale = self._sale()
        self._item(sale, "150.00", service=self.cut)
        self._item(sale, "50.00", service=self.colour, quantity=1)
        sale2 = self._sale(day_offset=1)
        self._item(sale2, "50.00", service=self.mani, quantity=2)
        rows = category_mix(self.salon, START, END)
        self.assertTrue(all(isinstance(r, CategoryMix) for r in rows))
        self.assertEqual([r.category_name for r in rows], ["Hair", "Nails"])
        hair, nails = rows
        self.assertEqual(hair.category, self.hair)
        self.assertEqual(hair.revenue, Decimal("200.00"))
        self.assertIsInstance(hair.revenue, Decimal)
        self.assertEqual((hair.quantity, hair.line_count, hair.sale_count, hair.service_count), (2, 2, 1, 2))
        self.assertEqual(hair.revenue_share_percent, Decimal("66.67"))
        self.assertEqual(hair.quantity_share_percent, Decimal("50.00"))
        self.assertEqual(nails.revenue_share_percent, Decimal("33.33"))
        self.assertEqual(nails.quantity_share_percent, Decimal("50.00"))
        self.assertEqual(sum(r.revenue_share_percent for r in rows), Decimal("100.00"))

    def test_uncategorized_snapshot_items(self):
        sale = self._sale()
        self._item(sale, "40.00", description="Mystery service")
        self._item(sale, "60.00", service=self.cut)
        rows = {r.category_name: r for r in category_mix(self.salon, START, END)}
        uncat = rows["Uncategorized"]
        self.assertIsNone(uncat.category)
        self.assertIsNone(uncat.category_id)
        self.assertEqual(uncat.revenue, Decimal("40.00"))
        self.assertEqual(uncat.service_count, 0)

    def test_completed_only_product_excluded_and_salon_scoped(self):
        for status in (Sale.Status.VOIDED, Sale.Status.OPEN):
            sale = self._sale(status=status)
            self._item(sale, "999.00", service=self.cut)
        sale = self._sale()
        self._item(sale, "999.00", kind=SaleItem.Kind.PRODUCT)
        other_sale = self._sale(salon=self.other)
        self._item(other_sale, "999.00", service=self.other_cut)
        self.assertEqual(category_mix(self.salon, START, END), [])

    def test_window_inclusive_created_fallback_and_reversed(self):
        for offset, price in ((0, "10.00"), (6, "20.00"), (-1, "999.00"), (7, "999.00")):
            sale = self._sale(day_offset=offset, completed=False)
            self._item(sale, price, service=self.cut)
        rows = category_mix(self.salon, START, END)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].revenue, Decimal("30.00"))
        self.assertEqual(category_mix(self.salon, END, START), [])
        self.assertEqual(category_mix(self.salon, START + timedelta(days=30), END + timedelta(days=30)), [])

    def test_same_name_categories_never_merge(self):
        twin_cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        twin = Service.objects.create(category=twin_cat, name="Trim", service_minutes=15)
        sale = self._sale()
        self._item(sale, "10.00", service=self.cut)
        self._item(sale, "20.00", service=twin)
        rows = category_mix(self.salon, START, END)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r.category_id for r in rows}, {self.hair.pk, twin_cat.pk})

    def test_zero_revenue_share_is_none(self):
        sale = self._sale()
        self._item(sale, "0.00", service=self.cut)
        rows = category_mix(self.salon, START, END)
        self.assertEqual(rows[0].revenue, Decimal("0.00"))
        self.assertIsNone(rows[0].revenue_share_percent)
        self.assertEqual(rows[0].quantity_share_percent, Decimal("100.00"))


class CategoryMixExportAndCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        cut = Service.objects.create(category=cat, name="Cut", service_minutes=45)
        sale = Sale.objects.create(salon=self.salon, status=Sale.Status.COMPLETED)
        stamp = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
        Sale.objects.filter(pk=sale.pk).update(created_at=stamp, completed_at=stamp)
        SaleItem.objects.create(sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1, unit_price=Decimal("80.00"), service=cut)
        SaleItem.objects.create(sale=sale, kind=SaleItem.Kind.SERVICE, quantity=1, unit_price=Decimal("20.00"), description="Mystery")

    def test_csv_matches_service_rows(self):
        text = export_category_mix_csv(self.salon, START, END)
        parsed = list(csv.reader(io.StringIO(text)))
        self.assertEqual(parsed[0], CATEGORY_MIX_FIELDNAMES)
        rows = category_mix(self.salon, START, END)
        self.assertEqual(len(parsed) - 1, len(rows))
        self.assertEqual(parsed[1][1], "Hair")
        self.assertEqual(parsed[1][2], "80.00")
        self.assertEqual(parsed[1][7], "80.00")
        self.assertEqual(parsed[2][0], "")  # uncategorized id empty
        self.assertEqual(parsed[2][1], "Uncategorized")

    def test_csv_empty_window_is_header_only(self):
        text = export_category_mix_csv(self.salon, START + timedelta(days=30), END + timedelta(days=30))
        self.assertEqual(text, ",".join(CATEGORY_MIX_FIELDNAMES) + "\n")

    def test_command_stdout_and_file(self):
        out = io.StringIO()
        call_command("export_category_mix", salon_id=self.salon.pk, start_date=START, end_date=END, stdout=out)
        self.assertEqual(out.getvalue(), export_category_mix_csv(self.salon, START, END))
        # Real filesystem writes are blocked in this test
        # environment, so --output is verified through a mocked
        # open, as in test_service_revenue.py.
        from unittest import mock
        mocked = mock.mock_open()
        with mock.patch("insights.management.commands.export_category_mix.open", mocked, create=True):
            file_out = io.StringIO()
            call_command("export_category_mix", salon_id=self.salon.pk, start_date=START, end_date=END, output="mix.csv", stdout=file_out)
        mocked.assert_called_once_with("mix.csv", "w", encoding="utf-8", newline="")
        mocked().write.assert_called_once_with(out.getvalue())
        self.assertEqual(file_out.getvalue(), "")

    def test_command_errors(self):
        with self.assertRaises(CommandError):
            call_command("export_category_mix", salon_id=self.salon.pk + 999, start_date=START, end_date=END, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_category_mix", salon_id=self.salon.pk, start_date="not-a-date", end_date=END, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_category_mix", salon_id=self.salon.pk, stdout=io.StringIO())
