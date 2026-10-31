import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.cashup import run_cashup
from checkout.cashup_history import _cashup_entry, cashup_history, list_cashups
from checkout.models import Cashup, Payment, Sale, SaleItem
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _stamp(day, hour=9):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour, 0)))


class CashupHistoryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def _cashup(self, salon, day, totals, total, hour=9, note=""):
        return Cashup.objects.create(
            salon=salon, period_start=_stamp(day, hour),
            period_end=_stamp(day, hour + 1),
            tender_totals={k: str(v) for k, v in totals.items()},
            total=Decimal(total), note=note)

    def test_empty_range_is_zeroed_summary_not_none(self):
        h = cashup_history(self.salon, DAY, DAY)
        self.assertEqual(h.entries, []); self.assertEqual(h.count, 0)
        self.assertEqual(h.total, Decimal("0.00")); self.assertIsNone(h.variance)
        for t in Payment.Method.values:
            self.assertEqual(h.by_tender[t], Decimal("0.00"))
            self.assertEqual(h.summary.by_tender[t], Decimal("0.00"))

    def test_multiple_cashups_same_day_all_listed_not_locked(self):
        a = self._cashup(self.salon, DAY, {"cash": "85.00"}, "85.00", hour=9)
        b = self._cashup(self.salon, DAY, {"cash": "15.00", "external": "50.00"}, "65.00", hour=17)
        h = cashup_history(self.salon, DAY, DAY)
        self.assertEqual(h.count, 2); self.assertEqual(len(h), 2)
        self.assertEqual({e.cashup_id for e in h.entries}, {a.pk, b.pk})
        self.assertEqual(h.entries[0].cashup_id, b.pk)  # newest period first
        self.assertFalse(h.entries[0].is_locked); self.assertEqual(h.cashups[0].pk, b.pk)

    def test_entry_totals_and_range_summary_by_tender(self):
        self._cashup(self.salon, DAY, {"cash": "85.00"}, "85.00", hour=9)
        self._cashup(self.salon, NEXT, {"cash": "15.00", "external": "50.00"}, "65.00", hour=9)
        h = cashup_history(self.salon, DAY, NEXT)
        e = h.entries[-1]
        self.assertEqual(e.tender_totals["cash"], Decimal("85.00"))
        self.assertEqual(e.tender_totals["external"], Decimal("0.00"))  # zero-filled
        self.assertEqual(e.total, Decimal("85.00"))
        self.assertEqual(h.summary.count, 2); self.assertEqual(h.summary.cashup_count, 2)
        self.assertEqual(h.summary.total, Decimal("150.00")); self.assertEqual(h.summary.total_taken, Decimal("150.00"))
        self.assertEqual(h.tender_totals["cash"], Decimal("100.00"))
        self.assertEqual(h.tender_totals["external"], Decimal("50.00"))
        self.assertEqual(h.by_tender, h.summary.by_tender)

    def test_other_salon_and_out_of_range_excluded(self):
        self._cashup(self.salon, DAY, {"cash": "85.00"}, "85.00")
        self._cashup(self.other, DAY, {"cash": "999.00"}, "999.00")
        self._cashup(self.salon, DAY + datetime.timedelta(days=7), {"cash": "999.00"}, "999.00")
        h = list_cashups(self.salon, DAY, NEXT)
        self.assertEqual(h.count, 1); self.assertEqual(h.total, Decimal("85.00"))

    def test_period_overlapping_range_boundary_is_included(self):
        c = Cashup.objects.create(salon=self.salon, period_start=_stamp(DAY, 23),
            period_end=_stamp(NEXT, 1), tender_totals={"cash": "10.00"}, total=Decimal("10.00"))
        h = cashup_history(self.salon, NEXT, NEXT)
        self.assertEqual([e.cashup_id for e in h.entries], [c.pk])

    def test_datetime_range(self):
        self._cashup(self.salon, DAY, {"cash": "85.00"}, "85.00", hour=9)
        self._cashup(self.salon, NEXT, {"cash": "999.00"}, "999.00", hour=9)
        h = cashup_history(self.salon, _stamp(DAY, 0), _stamp(DAY, 23))
        self.assertEqual(h.count, 1); self.assertEqual(h.total, Decimal("85.00"))

    def test_variance_none_when_model_records_no_expected(self):
        self._cashup(self.salon, DAY, {"cash": "85.00"}, "85.00")
        e = cashup_history(self.salon, DAY, DAY).entries[0]
        self.assertFalse(e.has_expected); self.assertIsNone(e.expected_total)
        self.assertIsNone(e.expected_tender_totals); self.assertIsNone(e.variance)
        self.assertIsNone(e.variance_by_tender)

    def test_variance_computed_when_record_carries_expected(self):
        c = self._cashup(self.salon, DAY, {"cash": "85.00", "external": "50.00"}, "135.00")
        c.expected_tender_totals = {"cash": "80.00", "external": "50.00"}
        e = _cashup_entry(c)
        self.assertTrue(e.has_expected); self.assertEqual(e.expected_total, Decimal("130.00"))
        self.assertEqual(e.variance, Decimal("5.00"))
        self.assertEqual(e.variance_by_tender["cash"], Decimal("5.00"))
        self.assertEqual(e.variance_by_tender["external"], Decimal("0.00"))

    def test_run_cashup_snapshots_appear_in_history(self):
        now = timezone.now()
        sale = Sale.objects.create(salon=self.salon, status=Sale.Status.COMPLETED, completed_at=now)
        SaleItem.objects.create(sale=sale, kind="service", description="Haircut", unit_price=Decimal("85.00"))
        Payment.objects.create(sale=sale, method="cash", amount=Decimal("85.00"), status=Payment.Status.COMPLETED)
        run_cashup(self.salon, now - timezone.timedelta(hours=1), now + timezone.timedelta(hours=1))
        h = cashup_history(self.salon, timezone.localdate(), timezone.localdate())
        self.assertEqual(h.count, 1); self.assertEqual(h.total, Decimal("85.00"))
        self.assertEqual(h.tender_totals["cash"], Decimal("85.00"))

    def test_history_is_read_only(self):
        self._cashup(self.salon, DAY, {"cash": "85.00"}, "85.00")
        before = list(Cashup.objects.values_list("id", "tender_totals", "total", "note"))
        cashup_history(self.salon, DAY, NEXT)
        self.assertEqual(Cashup.objects.count(), 1)
        self.assertEqual(list(Cashup.objects.values_list("id", "tender_totals", "total", "note")), before)

    def test_inverted_range_and_missing_args_raise(self):
        with self.assertRaises(ValueError): cashup_history(self.salon, NEXT, DAY)
        with self.assertRaises(ValueError): cashup_history(None, DAY, DAY)
        with self.assertRaises(ValueError): cashup_history(self.salon, None, DAY)
