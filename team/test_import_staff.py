"""Tests for the import_staff management command.

Fixtures are tiny hand-written JSON documents in the staff extract
shape — unit logic only, no real salon data, synthetic ids only.
"""
import io
import json
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon, StaffLevel
from team.models import StaffMember

FIXTURE = [
    {"staffId": "stf-1", "firstName": "Test", "lastName": "Stylist",
     "staffCategoryName": "Artist Level 1", "archived": False},
    {"staffId": "stf-2", "firstName": "Solo", "lastName": "",
     "staffCategoryName": "Artist Level 2"},
    {"id": "stf-3", "name": "Fallback Name"},
    {"firstName": "No", "lastName": "StableId"},  # no id: skipped
    {"staffId": "stf-4"},  # no name: skipped
    "not-a-dict",
]


def _write(payload):
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fh)
    fh.close()
    return fh.name


class ImportStaffTests(TestCase):
    def run_import(self, payload=FIXTURE, **kwargs):
        out = io.StringIO()
        call_command("import_staff", _write(payload), stdout=out, **kwargs)
        return out.getvalue()

    def test_imports_fields_and_stores_staff_id(self):
        out = self.run_import()
        self.assertIn("IMPORT_SUMMARY", out)
        self.assertIn('"created": 3', out)
        self.assertIn('"skipped": 3', out)
        member = StaffMember.objects.get(external_id="stf-1")
        self.assertEqual(member.display_name, "Test Stylist")
        self.assertEqual(member.salon.name, "My Salon")
        self.assertEqual(
            StaffMember.objects.get(external_id="stf-2").display_name, "Solo")
        self.assertEqual(
            StaffMember.objects.get(external_id="stf-3").display_name,
            "Fallback Name")

    def test_category_links_to_existing_price_book_level(self):
        salon = Salon.objects.create(name="My Salon")
        level = StaffLevel.objects.create(salon=salon, name="Artist Level 1")
        out = self.run_import()
        self.assertIn('"levels_linked": 2', out)
        member = StaffMember.objects.get(external_id="stf-1")
        self.assertEqual(member.staff_level, level)
        self.assertEqual(
            StaffLevel.objects.filter(salon=salon, name="Artist Level 1").count(), 1)
        self.assertEqual(
            StaffMember.objects.get(external_id="stf-2").staff_level.name,
            "Artist Level 2")
        self.assertIsNone(
            StaffMember.objects.get(external_id="stf-3").staff_level)

    def test_reimport_updates_level_and_online_bookable(self):
        self.run_import()
        member = StaffMember.objects.get(external_id="stf-1")
        self.assertEqual(member.staff_level.name, "Artist Level 1")
        changed = json.loads(json.dumps(FIXTURE))
        changed[0]["staffCategoryName"] = "Artist Level 2"
        changed[0]["hideFromOnlineBookings"] = True
        self.run_import(payload=changed)
        member.refresh_from_db()
        self.assertEqual(member.staff_level.name, "Artist Level 2")
        self.assertFalse(member.online_bookable)

    def test_hide_from_online_bookings_maps_inverted(self):
        payload = [
            {"staffId": "stf-h", "firstName": "Hidden",
             "hideFromOnlineBookings": True},
            {"staffId": "stf-v", "firstName": "Visible",
             "hideFromOnlineBookings": False},
        ]
        self.run_import(payload=payload)
        self.assertFalse(
            StaffMember.objects.get(external_id="stf-h").online_bookable)
        self.assertTrue(
            StaffMember.objects.get(external_id="stf-v").online_bookable)

    def test_missing_category_and_hide_flag_leave_fields_untouched(self):
        self.run_import()
        salon = Salon.objects.get(name="My Salon")
        level = StaffLevel.objects.create(salon=salon, name="Level 9")
        member = StaffMember.objects.get(external_id="stf-1")
        member.staff_level = level
        member.online_bookable = False
        member.save()
        changed = json.loads(json.dumps(FIXTURE))
        changed[0]["firstName"] = "Renamed"
        del changed[0]["staffCategoryName"]  # missing: must NOT clear level
        self.run_import(payload=changed)
        member.refresh_from_db()
        self.assertEqual(member.display_name, "Renamed Stylist")
        self.assertEqual(member.staff_level, level)
        self.assertFalse(member.online_bookable)

    def test_rerun_is_idempotent_and_updates_in_place(self):
        self.run_import()
        out = self.run_import()
        self.assertIn('"created": 0', out)
        self.assertIn('"updated": 3', out)
        self.assertEqual(StaffMember.objects.count(), 3)

    def test_same_external_id_in_another_salon_is_separate(self):
        self.run_import()
        self.run_import(salon="Other Salon")
        self.assertEqual(StaffMember.objects.count(), 6)
        self.assertEqual(
            StaffMember.objects.filter(salon__name="Other Salon").count(), 3)

    def test_missing_file_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("import_staff", "/nonexistent/staff.json")

    def test_invalid_json_raises_command_error(self):
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        fh.write("{not json")
        fh.close()
        with self.assertRaises(CommandError):
            call_command("import_staff", fh.name)
