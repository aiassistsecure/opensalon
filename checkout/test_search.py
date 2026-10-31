import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale, SaleItem
from checkout.search import search_sales
from clients.models import Client
from saloncore.models import Salon


class SaleSearchTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.ana = Client.objects.create(
            salon=self.salon, first_name="Ana", last_name="Lopez"
        )
        self.bob = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Anand"
        )
        self.day = datetime.date(2026, 10, 3)

    def _at(self, day, hour=12):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, 0)),
            datetime.timezone.utc,
        )

    def _sale(self, salon=None, client=None, items=(("service", "85.00", 1),),
              status=Sale.Status.COMPLETED, day=None, completed=True):
        sale = Sale.objects.create(
            salon=salon or self.salon, client=client, status=status
        )
        for kind, price, qty in items:
            SaleItem.objects.create(
                sale=sale, kind=kind, description=kind,
                unit_price=Decimal(price), quantity=qty,
            )
        stamp = self._at(day or self.day)
        updates = {"created_at": stamp}
        if completed:
            updates["completed_at"] = stamp
        Sale.objects.filter(pk=sale.pk).update(**updates)
        sale.refresh_from_db()
        return sale

    def test_no_filters_returns_all_non_voided_newest_first(self):
        older = self._sale(day=self.day - datetime.timedelta(days=1))
        newer = self._sale(day=self.day)
        self._sale(status=Sale.Status.VOIDED)
        results = search_sales(self.salon)
        self.assertEqual([s.pk for s in results], [newer.pk, older.pk])
        self.assertEqual(results[0].search_total, Decimal("85.00"))

    def test_name_fragment_matches_first_last_and_full(self):
        ana_sale = self._sale(client=self.ana)
        bob_sale = self._sale(client=self.bob)
        self._sale()  # walk-in: no client, never matches a name search
        self.assertEqual(
            [s.pk for s in search_sales(self.salon, client_name="ana")],
            [bob_sale.pk, ana_sale.pk],
        )
        self.assertEqual(
            [s.pk for s in search_sales(self.salon, client_name="LOPEZ")],
            [ana_sale.pk],
        )
        self.assertEqual(
            [s.pk for s in search_sales(self.salon, client_name="bob an")],
            [bob_sale.pk],
        )
        self.assertEqual(search_sales(self.salon, client_name="zzz"), [])

    def test_blank_name_is_no_filter(self):
        sale = self._sale()
        self.assertEqual(
            [s.pk for s in search_sales(self.salon, client_name="  ")],
            [sale.pk],
        )

    def test_date_range_is_inclusive_and_uses_local_days(self):
        first = self._sale(day=self.day)
        last = self._sale(day=self.day + datetime.timedelta(days=2))
        self._sale(day=self.day + datetime.timedelta(days=3))
        self._sale(day=self.day - datetime.timedelta(days=1))
        results = search_sales(
            self.salon, date_from=self.day,
            date_to=self.day + datetime.timedelta(days=2),
        )
        self.assertEqual([s.pk for s in results], [last.pk, first.pk])

    def test_open_ended_ranges(self):
        old = self._sale(day=self.day - datetime.timedelta(days=5))
        new = self._sale(day=self.day)
        self.assertEqual(
            [s.pk for s in search_sales(self.salon, date_from=self.day)],
            [new.pk],
        )
        self.assertEqual(
            [s.pk for s in search_sales(self.salon, date_to=self.day)],
            [new.pk, old.pk],
        )

    def test_uncompleted_sale_attributed_by_created_at(self):
        sale = self._sale(completed=False)
        self.assertEqual(
            [s.pk for s in search_sales(
                self.salon, date_from=self.day, date_to=self.day)],
            [sale.pk],
        )
        self.assertEqual(
            search_sales(
                self.salon,
                date_from=self.day + datetime.timedelta(days=1),
            ),
            [],
        )

    def test_min_total_is_inclusive_and_uses_line_totals(self):
        big = self._sale(items=(("product", "20.00", 2),
                                ("service", "60.00", 1)))  # 100.00
        self._sale(items=(("service", "99.99", 1),))
        self.assertEqual(
            [s.pk for s in search_sales(
                self.salon, min_total=Decimal("100.00"))],
            [big.pk],
        )
        self.assertEqual(
            search_sales(self.salon, min_total="100.01"), []
        )

    def test_voided_excluded_unless_requested(self):
        live = self._sale()
        voided = self._sale(status=Sale.Status.VOIDED)
        self.assertEqual(
            [s.pk for s in search_sales(self.salon)], [live.pk]
        )
        self.assertEqual(
            {s.pk for s in search_sales(self.salon, include_voided=True)},
            {live.pk, voided.pk},
        )

    def test_cross_salon_isolation(self):
        mine = self._sale(client=self.ana)
        self._sale(salon=self.other, client=None)
        self.assertEqual(
            [s.pk for s in search_sales(self.salon, client_name="ana")],
            [mine.pk],
        )
        self.assertEqual(search_sales(self.other, client_name="ana"), [])

    def test_filters_combine(self):
        keep = self._sale(client=self.ana,
                          items=(("service", "120.00", 1),))
        self._sale(client=self.ana, items=(("service", "10.00", 1),))
        self._sale(client=self.bob, items=(("service", "120.00", 1),))
        results = search_sales(
            self.salon, client_name="lopez", min_total=Decimal("50.00"),
            date_from=self.day, date_to=self.day,
        )
        self.assertEqual([s.pk for s in results], [keep.pk])

    def test_read_only_records_nothing(self):
        self._sale(client=self.ana)
        search_sales(self.salon, client_name="ana")
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(SaleItem.objects.count(), 1)

    def test_invalid_arguments_raise(self):
        with self.assertRaises(ValueError):
            search_sales(None)
        with self.assertRaises(ValueError):
            search_sales(self.salon, min_total="not-a-number")
        with self.assertRaises(ValueError):
            search_sales(self.salon, min_total=Decimal("-1.00"))
        with self.assertRaises(ValueError):
            search_sales(
                self.salon, date_from=self.day,
                date_to=self.day - datetime.timedelta(days=1),
            )
