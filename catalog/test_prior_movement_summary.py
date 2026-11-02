"""Tests for prior-period movement summary: service, export, command."""
import csv
import io
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from catalog.models import Product, StockMovement
from catalog.movement_summary import movement_summary
from catalog.prior_movement_summary import prior_movement_summary
from catalog.prior_movement_summary_export import (
    PRIOR_MOVEMENT_SUMMARY_FIELDNAMES, export_prior_movement_summary,
    export_prior_movement_summary_csv)
from saloncore.models import Salon

DAY = date(2026, 10, 3)
PRIOR_DAY = DAY - timedelta(days=1)
RECEIVE = StockMovement.Kind.RECEIVE
SALE = StockMovement.Kind.SALE
ADJUSTMENT = StockMovement.Kind.ADJUSTMENT


class PriorMovementSummaryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, sku="", barcode=""):
        return Product.objects.create(salon=self.salon, name=name, sku=sku,
                                      barcode=barcode, price=Decimal("10.00"))

    def move(self, product, delta, kind=RECEIVE, on=None):
        movement = StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta)
        moment = timezone.make_aware(datetime(on.year, on.month, on.day, 12, 0))
        StockMovement.objects.filter(pk=movement.pk).update(created_at=moment)

    def seed(self):
        alpha = self.make_product("Alpha", sku="A-1", barcode="111")
        beta = self.make_product("Beta", sku="B-1", barcode="222")
        gamma = self.make_product("Gamma", sku="G-1", barcode="333")
        self.move(alpha, 10, on=PRIOR_DAY)
        self.move(alpha, -2, kind=SALE, on=PRIOR_DAY)
        self.move(gamma, 5, on=PRIOR_DAY)
        self.move(alpha, 10, on=DAY)
        self.move(alpha, -3, kind=SALE, on=DAY)
        self.move(alpha, -1, kind=ADJUSTMENT, on=DAY)
        self.move(beta, 4, on=DAY)
        return alpha, beta, gamma

    def test_both_windows_verbatim_and_salon_totals(self):
        self.seed()
        r = prior_movement_summary(DAY, DAY, salon=self.salon)
        self.assertEqual((r.start_date, r.end_date, r.prior_start_date,
                          r.prior_end_date), (DAY, DAY, PRIOR_DAY, PRIOR_DAY))
        self.assertEqual((r.days, r.salon_id), (1, self.salon.pk))
        self.assertEqual(r.current, movement_summary(DAY, DAY, salon=self.salon))
        self.assertEqual(r.prior, movement_summary(PRIOR_DAY, PRIOR_DAY,
                                                   salon=self.salon))
        self.assertEqual((r.movement_count.current, r.movement_count.prior,
                          r.movement_count.delta,
                          r.movement_count.percent_change),
                         (4, 3, 1, Decimal("33.33")))
        self.assertEqual((r.net_delta.current, r.net_delta.prior,
                          r.net_delta.delta, r.net_delta.percent_change),
                         (10, 13, -3, Decimal("-23.08")))
        recv = r.by_kind[RECEIVE]
        self.assertEqual((recv.current, recv.prior, recv.delta,
                          recv.percent_change), (14, 15, -1, Decimal("-6.67")))
        counts = r.by_kind_counts[RECEIVE]
        self.assertEqual((counts.current, counts.prior, counts.delta,
                          counts.percent_change), (2, 2, 0, Decimal("0.00")))
        self.assertEqual(r.by_kind_counts[SALE].current, 1)

    def test_per_product_union_and_deltas(self):
        alpha, beta, gamma = self.seed()
        r = prior_movement_summary(DAY, DAY, salon=self.salon)
        self.assertEqual([row.product_name for row in r.by_product],
                         ["Alpha", "Beta", "Gamma"])
        a = r.for_product(alpha)
        self.assertEqual((a.sku, a.barcode), ("A-1", "111"))
        self.assertEqual((a.movement_count.current, a.movement_count.prior,
                          a.movement_count.delta,
                          a.movement_count.percent_change),
                         (3, 2, 1, Decimal("50.00")))
        self.assertEqual((a.net_delta.current, a.net_delta.prior,
                          a.net_delta.delta, a.net_delta.percent_change),
                         (6, 8, -2, Decimal("-25.00")))
        self.assertEqual((a.by_kind[SALE].current, a.by_kind[SALE].prior,
                          a.by_kind[SALE].delta,
                          a.by_kind[SALE].percent_change),
                         (-3, -2, -1, Decimal("50.00")))
        b = r.for_product(beta.pk)  # current only: prior zero
        self.assertEqual((b.movement_count.current, b.movement_count.prior),
                         (1, 0))
        self.assertIsNone(b.movement_count.percent_change)
        self.assertIsNone(b.net_delta.percent_change)
        g = r.for_product(gamma)  # prior only: current zero
        self.assertEqual((g.net_delta.current, g.net_delta.prior,
                          g.net_delta.delta, g.net_delta.percent_change),
                         (0, 5, -5, Decimal("-100.00")))
        payload = r.as_dict()
        self.assertEqual(payload["prior_start_date"], PRIOR_DAY.isoformat())
        self.assertEqual(payload["by_product"][0]["product_id"], alpha.pk)

    def test_equal_length_multi_day_and_errors(self):
        self.seed()
        start = DAY - timedelta(days=1)
        r = prior_movement_summary(start, DAY, salon=self.salon)
        self.assertEqual((r.days, r.prior_start_date, r.prior_end_date),
                         (2, start - timedelta(days=2),
                          start - timedelta(days=1)))
        for call in (lambda: prior_movement_summary(
                         DAY + timedelta(days=1), DAY, salon=self.salon),
                     lambda: prior_movement_summary(None, DAY,
                                                    salon=self.salon),
                     lambda: prior_movement_summary("2026-10-03", DAY),
                     lambda: export_prior_movement_summary_csv(
                         DAY + timedelta(days=1), DAY, salon=self.salon)):
            with self.assertRaises(ValueError):
                call()

    def test_empty_windows_are_zeroed(self):
        empty = DAY + timedelta(days=30)
        r = prior_movement_summary(empty, empty, salon=self.salon)
        self.assertEqual(r.by_product, [])
        self.assertEqual((r.movement_count.current, r.movement_count.prior),
                         (0, 0))
        self.assertIsNone(r.movement_count.percent_change)
        self.assertIsNone(r.net_delta.percent_change)
        rows = export_prior_movement_summary(empty, empty, salon=self.salon)
        self.assertEqual((len(rows), rows[0]["product_id"]), (1, ""))

    def test_export_dicts_and_csv_agree(self):
        alpha, _beta, _gamma = self.seed()
        rows = export_prior_movement_summary(DAY, DAY, salon=self.salon)
        self.assertEqual(list(rows[0].keys()),
                         PRIOR_MOVEMENT_SUMMARY_FIELDNAMES)
        self.assertEqual(len(rows), 4)  # total + 3 products
        total, first = rows[0], rows[1]
        self.assertEqual((total["product_name"], total["current_net_delta"],
                          total["net_delta_percent_change"]),
                         ("", 10, Decimal("-23.08")))
        self.assertEqual((first["product_id"], first["current_movement_count"],
                          first["prior_movement_count"],
                          first["movement_count_percent_change"]),
                         (alpha.pk, 3, 2, Decimal("50.00")))
        self.assertEqual(first["current_by_kind"][RECEIVE], 10)
        text = export_prior_movement_summary_csv(DAY, DAY, salon=self.salon)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(parsed[0].keys()),
                         PRIOR_MOVEMENT_SUMMARY_FIELDNAMES)
        self.assertEqual((parsed[0]["current_movement_count"],
                          parsed[0]["movement_count_percent_change"],
                          parsed[0]["prior_end_date"]),
                         ("4", "33.33", PRIOR_DAY.isoformat()))
        self.assertEqual(json.loads(parsed[1]["current_by_kind"]),
                         {"adjustment": -1, "receive": 10, "sale": -3})
        self.assertEqual(json.loads(parsed[1]["by_kind_percent_change"])["sale"],
                         "50.00")
        beta_row = next(r for r in parsed if r["product_name"] == "Beta")
        self.assertEqual(beta_row["net_delta_percent_change"], "")

    def test_command_stdout_file_and_errors(self):
        self.seed()
        expected = export_prior_movement_summary_csv(DAY, DAY, salon=self.salon)
        out = io.StringIO()
        call_command("export_prior_movement_summary", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), expected)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_prior_movement_summary",
                         salon_id=self.salon.pk, start_date="2026-10-03",
                         end_date="2026-10-03", output=path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), expected)
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start_date=DAY,
                            end_date=DAY),
                       dict(salon_id=self.salon.pk,
                            start_date=DAY + timedelta(days=1), end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date="bad",
                            end_date=DAY),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_movement_summary",
                             stdout=io.StringIO(), **kwargs)
