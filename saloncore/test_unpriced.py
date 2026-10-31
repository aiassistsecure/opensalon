from decimal import Decimal

from django.test import TestCase

from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from saloncore.unpriced import (
    fully_unpriced_services,
    price_book_completeness,
    unpriced_services,
)


class UnpricedServicesTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint")
        self.other = Salon.objects.create(name="Other")
        self.cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.other_cat = ServiceCategory.objects.create(
            salon=self.other, name="Hair"
        )
        self.junior = StaffLevel.objects.create(salon=self.salon, name="Junior")
        self.senior = StaffLevel.objects.create(salon=self.salon, name="Senior")
        self.unpriced = Service.objects.create(
            category=self.cat, name="Unpriced Cut", service_minutes=30
        )
        self.full = Service.objects.create(
            category=self.cat, name="Full Cut", service_minutes=30
        )
        self.partial = Service.objects.create(
            category=self.cat, name="Partial Cut", service_minutes=30
        )
        for level in (self.junior, self.senior):
            ServicePrice.objects.create(
                service=self.full, staff_level=level, amount=Decimal("50.00")
            )
        ServicePrice.objects.create(
            service=self.partial, staff_level=self.junior, amount=Decimal("40.00")
        )

    def test_fully_unpriced_listed(self):
        result = unpriced_services(self.salon)
        ids = [e.service_id for e in result]
        self.assertEqual(ids, [self.unpriced.pk])
        entry = result[0]
        self.assertEqual(entry.service_name, "Unpriced Cut")
        self.assertEqual(entry.category_id, self.cat.pk)
        self.assertEqual(entry.category_name, "Hair")
        self.assertEqual(
            {lvl.level_id for lvl in entry.missing_levels},
            {self.junior.pk, self.senior.pk},
        )
        data = entry.to_dict()
        self.assertEqual(data["service_id"], self.unpriced.pk)
        self.assertEqual(
            set(data["missing_level_ids"]), {self.junior.pk, self.senior.pk}
        )

    def test_priced_for_all_levels_excluded(self):
        for func_result in (
            unpriced_services(self.salon),
            unpriced_services(self.salon, staff_level=self.junior),
            unpriced_services(self.salon, staff_level=self.senior),
            fully_unpriced_services(self.salon),
        ):
            self.assertNotIn(self.full.pk, [e.service_id for e in func_result])

    def test_per_level_gap_detection(self):
        junior_gaps = unpriced_services(self.salon, staff_level=self.junior)
        self.assertEqual(
            [e.service_id for e in junior_gaps], [self.unpriced.pk]
        )
        senior_gaps = unpriced_services(self.salon, staff_level=self.senior)
        self.assertEqual(
            {e.service_id for e in senior_gaps},
            {self.unpriced.pk, self.partial.pk},
        )
        partial_entry = next(
            e for e in senior_gaps if e.service_id == self.partial.pk
        )
        self.assertEqual(
            [lvl.level_id for lvl in partial_entry.missing_levels],
            [self.senior.pk],
        )

    def test_inactive_services_excluded(self):
        Service.objects.create(
            category=self.cat, name="Retired", service_minutes=30, active=False
        )
        names = [e.service_name for e in unpriced_services(self.salon)]
        self.assertNotIn("Retired", names)
        names = [
            e.service_name
            for e in unpriced_services(self.salon, staff_level=self.senior)
        ]
        self.assertNotIn("Retired", names)

    def test_other_salon_excluded(self):
        Service.objects.create(
            category=self.other_cat, name="Other Unpriced", service_minutes=30
        )
        result = unpriced_services(self.salon)
        self.assertNotIn("Other Unpriced", [e.service_name for e in result])
        other_result = unpriced_services(self.other)
        self.assertEqual(
            [e.service_name for e in other_result], ["Other Unpriced"]
        )

    def test_staff_level_from_other_salon_rejected(self):
        foreign = StaffLevel.objects.create(salon=self.other, name="Foreign")
        with self.assertRaises(ValueError):
            unpriced_services(self.salon, staff_level=foreign)

    def test_read_only(self):
        before = (
            Service.objects.count(),
            ServicePrice.objects.count(),
            StaffLevel.objects.count(),
        )
        unpriced_services(self.salon)
        unpriced_services(self.salon, staff_level=self.senior)
        price_book_completeness(self.salon, staff_level=self.senior)
        after = (
            Service.objects.count(),
            ServicePrice.objects.count(),
            StaffLevel.objects.count(),
        )
        self.assertEqual(before, after)

    def test_completeness_report_structure(self):
        report = price_book_completeness(self.salon, staff_level=self.senior)
        self.assertEqual(report["salon_id"], self.salon.pk)
        self.assertEqual(report["fully_unpriced_count"], 1)
        self.assertEqual(report["fully_unpriced"][0]["service_name"], "Unpriced Cut")
        self.assertEqual(report["missing_for_level_count"], 2)
        self.assertEqual(report["staff_level_id"], self.senior.pk)
