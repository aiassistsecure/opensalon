"""StaffService leg: salon_data export/import preserves the matrix.

Synthetic records only. The capability matrix (team.StaffService)
was the one model with no salon_data section: a round trip silently
lost it, including ``enabled=False`` rows — once any row exists for
a service, the rows are the whole truth, so dropping a False row
would flip a service back to the price-book fallback.
"""
import hashlib
import io
import json
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon, Service, ServiceCategory, StaffLevel
from saloncore.models import ServicePrice
from team.models import StaffMember, StaffService


def _matrix():
    """The restored matrix as a set of natural keys + enabled."""
    return {
        (link.staff_member.external_id or link.staff_member.display_name,
         link.service.external_id or link.service.name, link.enabled)
        for link in StaffService.objects.select_related(
            "staff_member", "service")
    }


def _digest(matrix):
    return hashlib.sha256(
        json.dumps(sorted(matrix), sort_keys=True).encode()).hexdigest()


class SalonDataStaffServicesTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Matrix Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")
        self.cut = Service.objects.create(
            category=self.category, name="Cut", external_id="svc-cut",
            service_minutes=45)
        self.color = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-color", service_minutes=60)
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6")
        ServicePrice.objects.create(
            service=self.cut, staff_level=self.level,
            amount=Decimal("50.00"))
        self.alice = StaffMember.objects.create(
            salon=self.salon, display_name="Alice",
            external_id="staff-a", staff_level=self.level)
        self.beth = StaffMember.objects.create(
            salon=self.salon, display_name="Beth",
            external_id="staff-b", staff_level=self.level)
        StaffService.objects.create(
            staff_member=self.alice, service=self.cut, enabled=True)
        StaffService.objects.create(
            staff_member=self.alice, service=self.color, enabled=False)
        StaffService.objects.create(
            staff_member=self.beth, service=self.color, enabled=True)

    def temp_path(self):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        return fh.name

    def export_data(self):
        path = self.temp_path()
        call_command("export_salon_data", path, stdout=io.StringIO())
        with open(path, encoding="utf-8") as fh:
            return path, json.load(fh)

    def write_data(self, path, data):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def run_import(self, path):
        out = io.StringIO()
        call_command("import_salon_data", path, stdout=out)
        return out.getvalue()

    def test_export_emits_staff_services_with_all_fields(self):
        _, data = self.export_data()
        self.assertEqual(data["counts"]["staff_services"], 3)
        self.assertEqual(len(data["staff_services"]), 3)
        by_pair = {
            (r["staff_member_external_id"], r["service_external_id"]): r
            for r in data["staff_services"]}
        row = by_pair[("staff-a", "svc-cut")]
        self.assertEqual(row["staff_member_id"], self.alice.id)
        self.assertEqual(row["service_id"], self.cut.id)
        self.assertTrue(row["enabled"])
        # The False row is exported verbatim, not dropped.
        self.assertFalse(by_pair[("staff-a", "svc-color")]["enabled"])
        self.assertTrue(by_pair[("staff-b", "svc-color")]["enabled"])

    def test_salon_filter_scopes_staff_services_via_staff_member(self):
        other = Salon.objects.create(name="Other Salon")
        cat = ServiceCategory.objects.create(salon=other, name="Nails")
        svc = Service.objects.create(
            category=cat, name="Manicure", service_minutes=30)
        staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        StaffService.objects.create(staff_member=staff, service=svc)
        path = self.temp_path()
        call_command("export_salon_data", path, salon="Matrix Salon",
                     stdout=io.StringIO())
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["counts"]["staff_services"], 3)
        call_command("export_salon_data", path, salon="Other Salon",
                     stdout=io.StringIO())
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["counts"]["staff_services"], 1)

    def test_round_trip_preserves_matrix_count_and_set_hash(self):
        before = _matrix()
        before_digest = _digest(before)
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(StaffService.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("staff_services=3", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(StaffService.objects.count(), len(before))
        self.assertEqual(_matrix(), before)
        self.assertEqual(_digest(_matrix()), before_digest)
        # The False row survived — no fallback flip.
        alice = StaffMember.objects.get(external_id="staff-a")
        color = Service.objects.get(external_id="svc-color")
        self.assertFalse(StaffService.objects.get(
            staff_member=alice, service=color).enabled)

    def test_reimport_is_idempotent_and_updates_enabled_in_place(self):
        path, data = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(StaffService.objects.count(), 3)
        row = next(r for r in data["staff_services"]
                   if r["service_external_id"] == "svc-color"
                   and r["staff_member_external_id"] == "staff-a")
        row["enabled"] = True
        self.write_data(path, data)
        self.run_import(path)
        self.assertEqual(StaffService.objects.count(), 3)
        self.assertEqual(_matrix(), {
            ("staff-a", "svc-cut", True), ("staff-a", "svc-color", True),
            ("staff-b", "svc-color", True)})

    def test_links_resolve_by_external_id_not_raw_pk(self):
        # No raw PK assumptions: file-local ids that name nothing
        # still restore when the *_external_id links resolve.
        path, data = self.export_data()
        for row in data["staff_services"]:
            row["staff_member_id"] = 999999
            row["service_id"] = 999999
        self.write_data(path, data)
        Salon.objects.all().delete()
        self.run_import(path)
        self.assertEqual(StaffService.objects.count(), 3)

    def test_missing_staff_services_section_imports_as_before(self):
        path, data = self.export_data()
        del data["staff_services"]
        del data["counts"]["staff_services"]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("staff_services=0", out)
        self.assertEqual(StaffService.objects.count(), 0)
        self.assertEqual(StaffMember.objects.count(), 2)

    def test_non_bool_enabled_fails_closed_with_zero_writes(self):
        path, data = self.export_data()
        data["staff_services"][0]["enabled"] = "false"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(StaffService.objects.count(), 0)

    def test_dangling_service_ref_fails_closed_with_zero_writes(self):
        path, data = self.export_data()
        data["staff_services"][0]["service_id"] = 999999
        data["staff_services"][0]["service_external_id"] = "svc-nope"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(StaffService.objects.count(), 0)

    def test_unknown_key_in_staff_services_named_not_dropped(self):
        path, data = self.export_data()
        data["staff_services"][0]["legacy_code"] = "X-1"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("staff_services.legacy_code", out)
        self.assertEqual(StaffService.objects.count(), 3)
