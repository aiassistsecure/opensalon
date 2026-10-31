import csv
import datetime
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from checkout.cashup_export import (
    BASE_FIELDNAMES,
    cashup_export_row,
    export_cashups,
    export_cashups_csv,
)
from checkout.models import Cashup
from saloncore.models import Salon


class CashupExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)

    def _at(self, day, hour=12):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour)),
            datetime.timezone.utc,
        )

    def _cashup(self, day=None, salon=None, totals=None, total="150.00",
                note="midday"):
        day = day or self.day
        return Cashup.objects.create(
            salon=salon or self.salon,
            period_start=self._at(day, 9), period_end=self._at(day, 17),
            tender_totals=totals if totals is not None else
            {"cash": "100.00", "external": "50.00"},
            total=Decimal(total), note=note,
        )

    def test_header_is_base_plus_sorted_tender_union(self):
        self._cashup(totals={"external": "50.00", "cash": "100.00"})
        self._cashup(totals={"cash": "10.00"}, total="10.00")
        text = export_cashups_csv(self.salon, self.day, self.day)
        header = text.splitlines()[0]
        self.assertEqual(
            header, ",".join(BASE_FIELDNAMES + ["cash", "external"]))
        rows = export_cashups(self.salon, self.day, self.day)
        for row in rows:
            self.assertEqual(
                list(row), BASE_FIELDNAMES + ["cash", "external"])

    def test_multi_tender_row_values_and_csv_agrees(self):
        cashup = self._cashup()
        rows = export_cashups(self.salon, self.day)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], cashup.pk)
        self.assertEqual(row["cashup_id"], cashup.pk)
        self.assertEqual(row["salon_id"], self.salon.pk)
        self.assertEqual(row["period_start"], cashup.period_start.isoformat())
        self.assertEqual(row["period_end"], cashup.period_end.isoformat())
        self.assertEqual(row["created_at"], cashup.created_at.isoformat())
        self.assertEqual(row["total"], "150.00")
        self.assertEqual(row["note"], "midday")
        self.assertEqual(row["cash"], "100.00")
        self.assertEqual(row["external"], "50.00")
        self.assertEqual(cashup_export_row(cashup)["cash"], "100.00")
        parsed = list(csv.DictReader(io.StringIO(
            export_cashups_csv(self.salon, self.day))))
        self.assertEqual(len(parsed), 1)
        for key, value in row.items():
            self.assertEqual(parsed[0][key], str(value))

    def test_missing_tender_in_a_row_is_zero_filled(self):
        self._cashup(totals={"cash": "10.00"}, total="10.00")
        self._cashup(totals={"external": "5.00"}, total="5.00")
        rows = export_cashups(self.salon, self.day, self.day)
        self.assertEqual(
            [(r["cash"], r["external"]) for r in rows],
            [("10.00", "0.00"), ("0.00", "5.00")])

    def test_empty_range_is_empty_list_and_header_only_csv(self):
        self._cashup()
        empty = self.day + datetime.timedelta(days=10)
        self.assertEqual(export_cashups(self.salon, empty, empty), [])
        self.assertEqual(
            export_cashups_csv(self.salon, empty, empty),
            ",".join(BASE_FIELDNAMES) + "\n")
        self.assertEqual(export_cashups(self.salon, empty, self.day), [])
        # Other salon's cashups never leak in.
        self.assertEqual(export_cashups(self.other, self.day, self.day), [])

    def test_period_outside_range_excluded_and_read_only(self):
        inside = self._cashup()
        self._cashup(day=self.day + datetime.timedelta(days=5))
        rows = export_cashups(self.salon, self.day, self.day)
        self.assertEqual([r["id"] for r in rows], [inside.pk])
        export_cashups_csv(self.salon, self.day, self.day)
        self.assertEqual(Cashup.objects.count(), 2)
        inside.refresh_from_db()
        self.assertEqual(inside.total, Decimal("150.00"))
        self.assertEqual(
            inside.tender_totals, {"cash": "100.00", "external": "50.00"})
