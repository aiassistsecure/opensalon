"""Tests for price-change window summary: service, export, command."""
import csv
import io
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.db.models.query import QuerySet as PlainQuerySet
from django.test import TestCase
from django.utils import timezone

from saloncore.models import (
    PriceChange, Salon, Service, ServiceCategory, ServicePrice, StaffLevel)
from saloncore.price_change_summary import price_change_summary
from saloncore.price_change_summary_export import (
    PRICE_CHANGE_SUMMARY_FIELDNAMES, export_price_change_summary,
    export_price_change_summary_csv)

START = date(2026, 10, 4)
END = date(2026, 10, 10)
PRIOR_START = date(2026, 9, 27)
PRIOR_END = date(2026, 10, 3)
D = Decimal


class PriceChangeSummaryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.color = self._price(self.salon, "Single Process Color")
        self.cut = self._price(self.salon, "Haircut")
        self.other_price = self._price(self.other, "Haircut")

    def _price(self, salon, service_name):
        category = ServiceCategory.objects.create(salon=salon, name="Cat")
        service = Service.objects.create(
            category=category, name=service_name, service_minutes=45)
        level = StaffLevel.objects.create(salon=salon, name="Level 6")
        return ServicePrice.objects.create(
            service=service, staff_level=level, amount=D("85.00"))

    def _change(self, price, old, new, on):
        change = PriceChange.objects.create(
            service_price=price, old_amount=old, new_amount=new)
        moment = timezone.make_aware(datetime(on.year, on.month, on.day, 12))
        # Append-only queryset blocks update(); re-stamp via a plain
        # queryset, the importer's creation-only idiom.
        PlainQuerySet(model=PriceChange, using="default").filter(
            pk=change.pk).update(changed_at=moment)
        return change

    def seed(self):
        # Prior window: +5 increase, one no-op, one no-old row.
        self._change(self.color, D("80.00"), D("85.00"), date(2026, 9, 28))
        self._change(self.color, D("85.00"), D("85.00"), date(2026, 9, 30))
        self._change(self.cut, None, D("50.00"), date(2026, 10, 2))
        # Current window: +10, -5, +10, one no-old row.
        self._change(self.color, D("85.00"), D("95.00"), date(2026, 10, 5))
        self._change(self.color, D("95.00"), D("90.00"), date(2026, 10, 7))
        self._change(self.cut, D("50.00"), D("60.00"), date(2026, 10, 8))
        self._change(self.cut, None, D("65.00"), date(2026, 10, 9))
        # Outside both windows / another salon: never counted.
        self._change(self.color, D("70.00"), D("80.00"), date(2026, 9, 20))
        self._change(self.other_price, D("1.00"), D("99.00"), date(2026, 10, 6))

    def test_both_windows_and_totals(self):
        self.seed()
        r = price_change_summary(self.salon, START, END)
        self.assertEqual((r.start_date, r.end_date, r.prior_start_date,
                          r.prior_end_date),
                         (START, END, PRIOR_START, PRIOR_END))
        self.assertEqual((r.days, r.salon_id), (7, self.salon.pk))
        self.assertEqual((r.current.change_count, r.current.increase_count,
                          r.current.decrease_count, r.current.net_amount_delta),
                         (4, 2, 1, D("15.00")))
        self.assertEqual((r.prior.change_count, r.prior.increase_count,
                          r.prior.decrease_count, r.prior.net_amount_delta),
                         (3, 1, 0, D("5.00")))
        self.assertEqual((r.change_count.current, r.change_count.prior,
                          r.change_count.delta, r.change_count.percent_change),
                         (4, 3, 1, D("33.33")))
        self.assertEqual((r.increase_count.delta, r.increase_count.percent_change),
                         (1, D("100.00")))
        self.assertEqual((r.decrease_count.current, r.decrease_count.prior,
                          r.decrease_count.delta), (1, 0, 1))
        self.assertIsNone(r.decrease_count.percent_change)
        self.assertEqual((r.net_amount_delta.current, r.net_amount_delta.prior,
                          r.net_amount_delta.delta,
                          r.net_amount_delta.percent_change),
                         (D("15.00"), D("5.00"), D("10.00"), D("200.00")))
        self.assertEqual(r.as_dict()["net_amount_delta"]["current"], D("15.00"))

    def test_per_service_union_and_no_old_rows(self):
        self.seed()
        r = price_change_summary(self.salon, START, END)
        self.assertEqual([s.service_name for s in r.by_service],
                         ["Haircut", "Single Process Color"])
        cut = r.for_service(self.cut.service)
        self.assertEqual((cut.change_count.current, cut.change_count.prior,
                          cut.change_count.percent_change),
                         (2, 1, D("100.00")))
        self.assertEqual((cut.net_amount_delta.current,
                          cut.net_amount_delta.prior,
                          cut.net_amount_delta.delta),
                         (D("10.00"), D("0.00"), D("10.00")))
        self.assertIsNone(cut.net_amount_delta.percent_change)
        self.assertIsNone(cut.increase_count.percent_change)
        color = r.for_service(self.color.service.pk)
        self.assertEqual((color.change_count.delta,
                          color.change_count.percent_change), (0, D("0.00")))
        self.assertEqual((color.decrease_count.current,
                          color.decrease_count.prior), (1, 0))
        self.assertEqual((color.net_amount_delta.current,
                          color.net_amount_delta.prior,
                          color.net_amount_delta.delta),
                         (D("5.00"), D("5.00"), D("0.00")))
        current_cut = next(row for row in r.current.by_service
                           if row["service_name"] == "Haircut")
        self.assertEqual(current_cut["change_count"], 2)  # no-old row counts
        self.assertEqual(current_cut["net_amount_delta"], D("10.00"))

    def test_errors_and_empty_windows(self):
        for call in (lambda: price_change_summary(self.salon, END, START),
                     lambda: price_change_summary(self.salon, None, END),
                     lambda: price_change_summary(self.salon, START, None),
                     lambda: price_change_summary(self.salon, "2026-10-04", END),
                     lambda: export_price_change_summary_csv(
                         self.salon, END, START)):
            with self.assertRaises(ValueError):
                call()
        empty = date(2027, 1, 7)
        r = price_change_summary(self.salon, empty, empty)
        self.assertEqual(r.by_service, [])
        self.assertEqual((r.change_count.current, r.change_count.prior), (0, 0))
        self.assertIsNone(r.change_count.percent_change)
        self.assertIsNone(r.net_amount_delta.percent_change)
        self.assertEqual(r.net_amount_delta.current, D("0.00"))
        rows = export_price_change_summary(self.salon, empty, empty)
        self.assertEqual((len(rows), rows[0]["service_id"]), (1, ""))

    def test_export_dicts_and_csv_agree(self):
        self.seed()
        rows = export_price_change_summary(self.salon, START, END)
        self.assertEqual(list(rows[0].keys()), PRICE_CHANGE_SUMMARY_FIELDNAMES)
        self.assertEqual(len(rows), 3)  # total + 2 services
        total = rows[0]
        self.assertEqual((total["service_name"], total["current_change_count"],
                          total["prior_change_count"],
                          total["change_count_percent_change"]),
                         ("", 4, 3, D("33.33")))
        self.assertEqual((total["current_net_amount_delta"],
                          total["net_amount_delta_percent_change"]),
                         (D("15.00"), D("200.00")))
        text = export_price_change_summary_csv(self.salon, START, END)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(parsed[0].keys()), PRICE_CHANGE_SUMMARY_FIELDNAMES)
        self.assertEqual((parsed[0]["current_net_amount_delta"],
                          parsed[0]["net_amount_delta_delta"],
                          parsed[0]["decrease_count_percent_change"],
                          parsed[0]["prior_end_date"]),
                         ("15.00", "10.00", "", PRIOR_END.isoformat()))

    def test_command_stdout_file_and_errors(self):
        self.seed()
        expected = export_price_change_summary_csv(self.salon, START, END)
        out = io.StringIO()
        call_command("export_price_change_summary", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        self.assertEqual(out.getvalue(), expected)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_price_change_summary",
                         salon_id=self.salon.pk, start_date="2026-10-04",
                         end_date="2026-10-10", output=path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), expected)
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start_date=START,
                            end_date=END),
                       dict(salon_id=self.salon.pk, start_date=END,
                            end_date=START),
                       dict(salon_id=self.salon.pk, start_date="bad",
                            end_date=END),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_price_change_summary",
                             stdout=io.StringIO(), **kwargs)
