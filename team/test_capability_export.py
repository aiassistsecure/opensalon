"""Capability matrix export: stored StaffService rows verbatim."""
import csv
import io

from django.test import TestCase

from saloncore.models import Salon, Service, ServiceCategory
from team.capability_export import (
    CAPABILITY_EXPORT_FIELDNAMES,
    EXPORT_FIELDNAMES,
    capability_matrix_csv,
    export_capability_matrix,
    export_capability_matrix_csv,
)
from team.models import StaffMember, StaffService


class CapabilityMatrixExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Matrix Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(name="Other", timezone="UTC")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        other_category = ServiceCategory.objects.create(
            salon=self.other_salon, name="Nails")
        self.cut = Service.objects.create(
            category=category, name="Cut", service_minutes=60)
        self.color = Service.objects.create(
            category=category, name="Color", service_minutes=90)
        self.other_service = Service.objects.create(
            category=other_category, name="Manicure", service_minutes=45)
        # PIN and email are set so the hygiene test is meaningful.
        self.dana = StaffMember.objects.create(
            salon=self.salon, display_name="Dana",
            pin="1234", email="dana@example.com")
        self.erin = StaffMember.objects.create(
            salon=self.salon, display_name="Erin")
        self.other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Other Dana")

    def _link(self, staff, service, enabled=True):
        return StaffService.objects.create(
            staff_member=staff, service=service, enabled=enabled)

    def test_header_and_dict_keys(self):
        self._link(self.dana, self.cut)
        text = export_capability_matrix_csv(self.salon)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], CAPABILITY_EXPORT_FIELDNAMES)
        self.assertEqual(EXPORT_FIELDNAMES, CAPABILITY_EXPORT_FIELDNAMES)
        records = export_capability_matrix(self.salon)
        self.assertEqual(len(records), 1)
        self.assertEqual(list(records[0].keys()),
                         CAPABILITY_EXPORT_FIELDNAMES)
        self.assertIs(capability_matrix_csv,
                      export_capability_matrix_csv)

    def test_rows_are_stored_values_verbatim(self):
        cut_dana = self._link(self.dana, self.cut, enabled=True)
        cut_erin = self._link(self.erin, self.cut, enabled=False)
        color_dana = self._link(self.dana, self.color, enabled=True)
        records = export_capability_matrix(self.salon)
        # StaffService ordering (service, then staff member),
        # expanding to the relations' own orderings: service by
        # (category, name) -- Color before Cut -- then staff by
        # display_name -- Dana before Erin.
        self.assertEqual([r["id"] for r in records],
                         [color_dana.pk, cut_dana.pk, cut_erin.pk])
        by_id = {r["id"]: r for r in records}
        self.assertEqual(by_id[cut_dana.pk], {
            "id": cut_dana.pk, "salon_id": self.salon.pk,
            "staff_member_id": self.dana.pk, "staff_name": "Dana",
            "service_id": self.cut.pk, "service_name": "Cut",
            "category_id": self.cut.category_id,
            "category_name": "Hair", "enabled": True})
        self.assertEqual(by_id[cut_erin.pk]["enabled"], False)
        self.assertEqual(by_id[color_dana.pk]["service_name"], "Color")
        # CSV agrees with the dict export, booleans rendered as stored.
        parsed = list(csv.DictReader(io.StringIO(
            export_capability_matrix_csv(self.salon))))
        self.assertEqual(len(parsed), len(records))
        parsed_by_id = {int(r["id"]): r for r in parsed}
        self.assertEqual(parsed_by_id[cut_dana.pk]["enabled"], "True")
        self.assertEqual(parsed_by_id[cut_erin.pk]["enabled"], "False")
        self.assertEqual(parsed_by_id[cut_dana.pk]["staff_name"], "Dana")

    def test_no_derived_rows_for_unlinked_services(self):
        # A service with no StaffService rows exports nothing:
        # the export reads stored rows only, it does not derive
        # performers from the price book or anywhere else.
        self._link(self.dana, self.cut)
        records = export_capability_matrix(self.salon)
        self.assertEqual([r["service_id"] for r in records],
                         [self.cut.pk])

    def test_salon_scoping_and_empty(self):
        self._link(self.dana, self.cut)
        self._link(self.other_staff, self.other_service)
        self.assertEqual(len(export_capability_matrix(self.salon)), 1)
        self.assertEqual(
            len(export_capability_matrix(self.other_salon)), 1)
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        self.assertEqual(export_capability_matrix(empty), [])
        self.assertEqual(
            export_capability_matrix_csv(empty),
            ",".join(CAPABILITY_EXPORT_FIELDNAMES) + "\n")

    def test_no_pin_or_email_anywhere(self):
        self._link(self.dana, self.cut)
        self.assertNotIn("pin", CAPABILITY_EXPORT_FIELDNAMES)
        self.assertNotIn("email", CAPABILITY_EXPORT_FIELDNAMES)
        text = export_capability_matrix_csv(self.salon)
        self.assertNotIn("1234", text)
        self.assertNotIn("dana@example.com", text)

    def test_read_only(self):
        self._link(self.dana, self.cut)
        before = StaffService.objects.count()
        export_capability_matrix(self.salon)
        export_capability_matrix_csv(self.salon)
        self.assertEqual(StaffService.objects.count(), before)
