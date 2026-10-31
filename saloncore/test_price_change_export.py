import csv
import io
import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from saloncore.models import (
    PriceChange,
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from saloncore.price_change_export import (
    PRICE_CHANGE_FIELDNAMES,
    export_price_changes,
    export_price_changes_csv,
    price_changes_csv,
)


class PriceChangeExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.price = self._price(self.salon, "Single Process Color", "Level 6")
        self.other_price = self._price(self.other, "Haircut", "Junior")

    def _price(self, salon, service_name, level_name):
        category = ServiceCategory.objects.create(salon=salon, name="Cat")
        service = Service.objects.create(
            category=category, name=service_name, service_minutes=45
        )
        level = StaffLevel.objects.create(salon=salon, name=level_name)
        return ServicePrice.objects.create(
            service=service, staff_level=level, amount=Decimal("85.00")
        )

    def _change(self, price=None, **kw):
        kw.setdefault("new_amount", Decimal("90.00"))
        return PriceChange.objects.create(service_price=price or self.price, **kw)

    def test_fieldnames_and_header(self):
        self.assertEqual(
            PRICE_CHANGE_FIELDNAMES,
            ["id", "service_price_id", "service_id", "service_name",
             "staff_level_id", "staff_level_name", "old_amount",
             "new_amount", "changed_by", "changed_at", "note"],
        )
        rows = list(csv.reader(io.StringIO(
            export_price_changes_csv(self.salon))))
        self.assertEqual(rows, [PRICE_CHANGE_FIELDNAMES])

    def test_rows_match_created_records(self):
        change = self._change(
            old_amount=Decimal("85.00"), new_amount=Decimal("90.00"),
            changed_by="Mark", note="Annual increase",
        )
        change.refresh_from_db()
        records = export_price_changes(self.salon)
        self.assertEqual(records, [{
            "id": change.pk,
            "service_price_id": self.price.pk,
            "service_id": self.price.service.pk,
            "service_name": "Single Process Color",
            "staff_level_id": self.price.staff_level.pk,
            "staff_level_name": "Level 6",
            "old_amount": "85.00",
            "new_amount": "90.00",
            "changed_by": "Mark",
            "changed_at": change.changed_at.isoformat(),
            "note": "Annual increase",
        }])
        self.assertEqual(json.loads(json.dumps(records)), records)

    def test_null_old_amount_and_blank_fields(self):
        self._change(new_amount=Decimal("85.00"))
        record = export_price_changes(self.salon)[0]
        self.assertIsNone(record["old_amount"])
        self.assertEqual(record["new_amount"], "85.00")
        self.assertEqual(record["changed_by"], "")
        self.assertEqual(record["note"], "")

    def test_chronological_order(self):
        first = self._change(new_amount=Decimal("90.00"))
        second = self._change(
            old_amount=Decimal("90.00"), new_amount=Decimal("95.00"))
        third = self._change(
            old_amount=Decimal("95.00"), new_amount=Decimal("100.00"))
        records = export_price_changes(self.salon)
        self.assertEqual(
            [r["id"] for r in records], [first.pk, second.pk, third.pk])

    def test_salon_isolation(self):
        self._change(note="Mine")
        self._change(price=self.other_price, note="Theirs")
        records = export_price_changes(self.salon)
        self.assertEqual([r["note"] for r in records], ["Mine"])
        self.assertEqual(
            [r["note"] for r in export_price_changes(self.other)], ["Theirs"])
        self.assertNotIn("Theirs", export_price_changes_csv(self.salon))

    def test_date_range_filter(self):
        change = self._change()
        change.refresh_from_db()
        today = timezone.localdate(change.changed_at)
        self.assertEqual(
            [r["id"] for r in export_price_changes(
                self.salon, start=today, end=today)],
            [change.pk],
        )
        self.assertEqual(
            export_price_changes(self.salon, start=today + timedelta(days=1)),
            [],
        )
        self.assertEqual(
            export_price_changes(self.salon, end=today - timedelta(days=1)),
            [],
        )
        # Datetime bounds are used as given (start-inclusive).
        self.assertEqual(
            [r["id"] for r in export_price_changes(
                self.salon, start=change.changed_at)],
            [change.pk],
        )

    def test_csv_matches_list_export_and_alias(self):
        self._change(old_amount=Decimal("85.00"), note="One, with comma")
        self._change(old_amount=Decimal("90.00"), note="Two")
        parsed = list(csv.DictReader(io.StringIO(
            export_price_changes_csv(self.salon))))
        records = export_price_changes(self.salon)
        self.assertEqual(len(parsed), len(records))
        for row, record in zip(parsed, records):
            self.assertEqual(int(row["id"]), record["id"])
            self.assertEqual(row["new_amount"], record["new_amount"])
            self.assertEqual(row["changed_at"], record["changed_at"])
            self.assertEqual(row["note"], record["note"])
        self.assertEqual(
            price_changes_csv(self.salon),
            export_price_changes_csv(self.salon),
        )

    def test_empty(self):
        self.assertEqual(export_price_changes(self.salon), [])
        self.assertEqual(
            export_price_changes_csv(self.salon),
            ",".join(PRICE_CHANGE_FIELDNAMES) + "\n",
        )

    def test_read_only(self):
        self._change()
        before = (
            PriceChange.objects.count(), ServicePrice.objects.count(),
            Service.objects.count(),
        )
        export_price_changes(self.salon)
        export_price_changes_csv(self.salon)
        self.assertEqual(
            (PriceChange.objects.count(), ServicePrice.objects.count(),
             Service.objects.count()),
            before,
        )
