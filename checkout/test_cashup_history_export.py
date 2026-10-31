import csv
import datetime
import io
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from checkout.cashup_history import CashupHistoryEntry, cashup_history
from checkout.cashup_history_export import (
    BASE_FIELDNAMES,
    EXPORT_FIELDNAMES,
    cashup_history_csv,
    cashup_history_export_row,
    export_cashup_history,
    export_cashup_history_csv,
)
from checkout.models import Cashup
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def _stamp(day, hour=9):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)))


class CashupHistoryExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def _cashup(self, salon, day, totals, total, hour=9, note=""):
        return Cashup.objects.create(
            salon=salon, period_start=_stamp(day, hour),
            period_end=_stamp(day, hour + 1),
            tender_totals={k: str(v) for k, v in totals.items()},
            total=Decimal(total), note=note)

    def test_header_and_row_keys_base_plus_sorted_tender_union(self):
        self._cashup(self.salon, DAY, {"external": "50.00"}, "50.00")
        self._cashup(self.salon, DAY, {"cash": "10.00"}, "10.00",
                     hour=17)
        self.assertEqual(EXPORT_FIELDNAMES, BASE_FIELDNAMES)
        text = export_cashup_history_csv(self.salon, DAY, DAY)
        # History zero-fills core tenders; union is sorted.
        self.assertEqual(
            text.splitlines()[0],
            ",".join(BASE_FIELDNAMES + ["cash", "external"]))
        for row in export_cashup_history(self.salon, DAY, DAY):
            self.assertEqual(
                list(row), BASE_FIELDNAMES + ["cash", "external"])
        self.assertEqual(
            list(_rows(text)[0]),
            BASE_FIELDNAMES + ["cash", "external"])

    def test_row_values_match_service_output(self):
        a = self._cashup(self.salon, DAY, {"cash": "85.00"}, "85.00",
                         hour=9, note="midday")
        history = cashup_history(self.salon, DAY, DAY)
        rows = export_cashup_history(self.salon, DAY, DAY)
        self.assertEqual(len(rows), 1)
        entry = history.entries[0]
        row = rows[0]
        self.assertEqual(row["id"], a.pk)
        self.assertEqual(row["cashup_id"], entry.cashup_id)
        self.assertEqual(row["salon_id"], entry.salon_id)
        self.assertEqual(row["period_start"],
                         entry.period_start.isoformat())
        self.assertEqual(row["period_end"],
                         entry.period_end.isoformat())
        self.assertEqual(row["created_at"],
                         entry.created_at.isoformat())
        self.assertEqual(row["note"], "midday")
        self.assertEqual(row["total"], "85.00")
        self.assertEqual(row["cash"], "85.00")
        self.assertEqual(row["external"], "0.00")  # zero-filled

    def test_delegates_to_service_verbatim(self):
        with mock.patch(
            "checkout.cashup_history_export.cashup_history",
            wraps=cashup_history,
        ) as spy:
            export_cashup_history(self.salon, DAY, DAY)
        spy.assert_called_once_with(self.salon, DAY, DAY)

    def test_multiple_cashups_same_day_all_export_not_locked(self):
        self._cashup(self.salon, DAY, {"cash": "85.00"}, "85.00",
                     hour=9)
        self._cashup(self.salon, DAY,
                     {"cash": "15.00", "external": "50.00"}, "65.00",
                     hour=17)
        rows = export_cashup_history(self.salon, DAY, DAY)
        self.assertEqual(len(rows), 2)
        # Service order is deterministic: newest period first.
        self.assertEqual([r["total"] for r in rows],
                         ["65.00", "85.00"])
        for row in rows:
            self.assertIs(row["is_locked"], False)
        parsed = _rows(export_cashup_history_csv(
            self.salon, DAY, DAY))
        self.assertEqual([r["is_locked"] for r in parsed],
                         ["False", "False"])

    def test_expected_and_variance_none_export_empty_not_zero(self):
        self._cashup(self.salon, DAY, {"cash": "85.00"}, "85.00")
        row = export_cashup_history(self.salon, DAY, DAY)[0]
        self.assertIsNone(row["expected_total"])
        self.assertIsNone(row["variance"])
        parsed = _rows(export_cashup_history_csv(
            self.salon, DAY, DAY))[0]
        self.assertEqual(parsed["expected_total"], "")
        self.assertEqual(parsed["variance"], "")
        self.assertNotEqual(parsed["expected_total"], "0.00")
        self.assertNotEqual(parsed["variance"], "0.00")

    def test_row_renders_expected_and_variance_when_present(self):
        cashup = self._cashup(self.salon, DAY, {"cash": "85.00"},
                              "85.00")
        entry = CashupHistoryEntry(
            cashup=cashup,
            tender_totals={"cash": Decimal("85.00")},
            total=Decimal("85.00"),
            expected_tender_totals={"cash": Decimal("80.00")},
            expected_total=Decimal("80.00"),
            variance_by_tender={"cash": Decimal("5.00")},
            variance=Decimal("5.00"))
        row = cashup_history_export_row(entry)
        self.assertEqual(row["expected_total"], "80.00")
        self.assertEqual(row["variance"], "5.00")
        self.assertEqual(row["expected_cash"], "80.00")
        self.assertEqual(row["variance_cash"], "5.00")

    def test_missing_tender_in_a_row_is_zero_filled(self):
        self._cashup(self.salon, DAY, {"cash": "10.00"}, "10.00",
                     hour=9)
        extra = self._cashup(self.salon, NEXT,
                             {"cash": "5.00", "card": "7.00"},
                             "12.00", hour=9)
        rows = export_cashup_history(self.salon, DAY, NEXT)
        self.assertEqual(
            list(rows[0]),
            BASE_FIELDNAMES + ["card", "cash", "external"])
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[extra.pk]["card"], "7.00")
        others = [r for r in rows if r["id"] != extra.pk]
        self.assertEqual(others[0]["card"], "0.00")

    def test_csv_agrees_with_list_and_alias(self):
        self._cashup(self.salon, DAY, {"cash": "85.00"}, "85.00",
                     note="midday")
        rows = export_cashup_history(self.salon, DAY, DAY)
        text = export_cashup_history_csv(self.salon, DAY, DAY)
        parsed = [
            {**r, "id": int(r["id"]), "cashup_id": int(r["cashup_id"]),
             "salon_id": int(r["salon_id"]),
             "expected_total": None, "variance": None,
             "is_locked": False}
            for r in _rows(text)
        ]
        self.assertEqual(parsed, rows)
        self.assertEqual(cashup_history_csv(self.salon, DAY, DAY),
                         text)

    def test_salon_scoping_and_empty_range(self):
        self._cashup(self.salon, DAY, {"cash": "85.00"}, "85.00")
        self._cashup(self.other, DAY, {"cash": "999.00"}, "999.00")
        rows = export_cashup_history(self.salon, DAY, DAY)
        self.assertEqual([r["salon_id"] for r in rows],
                         [self.salon.pk])
        empty = DAY + datetime.timedelta(days=10)
        self.assertEqual(export_cashup_history(self.salon, empty,
                                               empty), [])
        self.assertEqual(
            export_cashup_history_csv(self.salon, empty, empty),
            ",".join(BASE_FIELDNAMES) + "\n")

    def test_service_errors_propagate(self):
        with self.assertRaises(ValueError):
            export_cashup_history(None, DAY, DAY)
        with self.assertRaises(ValueError):
            export_cashup_history(self.salon, NEXT, DAY)
        with self.assertRaises(ValueError):
            export_cashup_history_csv(self.salon, None, DAY)

    def test_read_only_records_unchanged(self):
        self._cashup(self.salon, DAY, {"cash": "85.00"}, "85.00")
        before = list(Cashup.objects.values_list(
            "id", "tender_totals", "total", "note"))
        export_cashup_history(self.salon, DAY, NEXT)
        export_cashup_history_csv(self.salon, DAY, NEXT)
        self.assertEqual(Cashup.objects.count(), 1)
        self.assertEqual(
            list(Cashup.objects.values_list(
                "id", "tender_totals", "total", "note")), before)
