from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from checkout.models import Sale, SaleItem
from clients.models import Client
from insights.client_value import ClientValue, client_value
from saloncore.models import Salon

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)  # Monday
END = date(2026, 11, 8)  # Sunday


class ClientValueTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.alice = Client.objects.create(
            salon=self.salon, first_name="Alice", last_name="Able"
        )
        self.bob = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Baker"
        )
        self.carol = Client.objects.create(
            salon=self.salon, first_name="Carol", last_name="Clark"
        )

    def _sale(self, client=None, *, day, price="50.00", salon=None,
              status=Sale.Status.COMPLETED):
        sale = Sale.objects.create(
            salon=salon or self.salon, client=client, status=status
        )
        stamp = datetime(2026, 11, 2, 12, 0, tzinfo=UTC) + timedelta(days=day)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=stamp, completed_at=stamp
        )
        if price is not None:
            SaleItem.objects.create(
                sale=sale, kind=SaleItem.Kind.SERVICE,
                quantity=1, unit_price=Decimal(price),
            )
        return sale

    def test_ranking_by_total_then_sale_count(self):
        self._sale(self.alice, day=0, price="60.00")
        self._sale(self.alice, day=1, price="40.00")  # total 100, 2 sales
        self._sale(self.bob, day=0, price="100.00")  # total 100, 1 sale
        self._sale(self.carol, day=2, price="150.00")  # total 150, 1 sale
        result = client_value(self.salon, START, END)
        self.assertEqual(
            [row.client for row in result.rows],
            [self.carol, self.alice, self.bob],
        )
        self.assertTrue(
            all(isinstance(row, ClientValue) for row in result.rows)
        )
        self.assertEqual(result.rows[1].total, Decimal("100.00"))
        self.assertEqual(result.rows[1].sale_count, 2)
        self.assertEqual(result.total, Decimal("350.00"))
        self.assertEqual(result.sale_count, 4)
        # The summary is iterable over its ranked rows.
        self.assertEqual(list(result), list(result.rows))
        self.assertEqual(len(result), 3)

    def test_window_bounds_inclusive_and_exclude_outside(self):
        self._sale(self.alice, day=0, price="10.00")  # start bound
        self._sale(self.alice, day=6, price="20.00")  # end bound
        self._sale(self.alice, day=-1, price="999.00")  # before
        self._sale(self.alice, day=7, price="999.00")  # after
        self._sale(self.alice, day=1, status=Sale.Status.OPEN)
        self._sale(self.alice, day=1, status=Sale.Status.VOIDED)
        result = client_value(self.salon, START, END)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0].total, Decimal("30.00"))
        self.assertEqual(result.rows[0].sale_count, 2)
        self.assertEqual(result.start_date, START)
        self.assertEqual(result.end_date, END)

    def test_salon_isolation(self):
        other_client = Client.objects.create(
            salon=self.other, first_name="Other", last_name="Client"
        )
        self._sale(self.alice, day=0, price="50.00")
        self._sale(other_client, day=0, price="999.00", salon=self.other)
        result = client_value(self.salon, START, END)
        self.assertEqual([row.client for row in result.rows], [self.alice])
        self.assertEqual(result.total, Decimal("50.00"))
        other_result = client_value(self.other, START, END)
        self.assertEqual(other_result.total, Decimal("999.00"))
        self.assertEqual(other_result.rows[0].client, other_client)

    def test_unattributed_bucket_excluded_from_rows(self):
        self._sale(self.alice, day=0, price="50.00")
        self._sale(None, day=1, price="30.00")  # no client
        self._sale(None, day=2, price="20.00")  # no client
        # A sale at this salon linked to another salon's client is
        # never guessed at: it also lands in unattributed.
        cross = Client.objects.create(
            salon=self.other, first_name="Cross", last_name="Salon"
        )
        self._sale(cross, day=1, price="5.00")
        result = client_value(self.salon, START, END)
        self.assertEqual([row.client for row in result.rows], [self.alice])
        self.assertEqual(result.unattributed_total, Decimal("55.00"))
        self.assertEqual(result.unattributed_sale_count, 3)
        self.assertEqual(result.unattributed, Decimal("55.00"))
        self.assertEqual(result.grand_total, Decimal("105.00"))
        self.assertEqual(
            result.total + result.unattributed_total, result.grand_total
        )

    def test_empty_and_reversed_windows_return_zeroes(self):
        for start, end in ((START, END), (END, START)):
            result = client_value(self.salon, start, end)
            self.assertEqual(result.rows, ())
            self.assertEqual(result.total, Decimal("0.00"))
            self.assertEqual(result.sale_count, 0)
            self.assertEqual(result.unattributed_total, Decimal("0.00"))
            self.assertEqual(result.unattributed_sale_count, 0)
