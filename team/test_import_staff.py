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


class ImportStaffDryRunTests(TestCase):
    """TF-12 wiring: --dry-run reports via saloncore.dry_run and
    writes nothing; a normal import of the same fixture still works."""

    # Record 1 carries a null staffCategoryName, record 2 omits it
    # entirely and carries an empty-string lastName, so the
    # report's null / missing / empty_string counts are distinct.
    FIXTURE = [
        {
            "staffId": "dry-1", "firstName": "Dry", "lastName": "Run",
            "staffCategoryName": None, "hideFromOnlineBookings": False,
            "legacySourceField": "not-mapped",
        },
        {"staffId": "dry-2", "firstName": "Second", "lastName": ""},
    ]

    def run_dry(self, payload=None):
        path = _write(self.FIXTURE if payload is None else payload)
        out = io.StringIO()
        call_command("import_staff", path, dry_run=True, stdout=out)
        return path, json.loads(out.getvalue())

    def test_dry_run_writes_nothing(self):
        self.run_dry()
        self.assertEqual(StaffMember.objects.count(), 0)
        self.assertEqual(StaffLevel.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 0)

    def test_dry_run_report_names_unmapped_key(self):
        path, report = self.run_dry()
        self.assertEqual(report["source"], path)
        self.assertEqual(report["record_count"], 2)
        self.assertIn("legacySourceField", report["unmapped_keys"])
        self.assertNotIn("legacySourceField", report["mapped_keys"])
        for mapped in ("staffId", "id", "firstName", "lastName",
                       "name", "displayName", "staffCategoryName",
                       "hideFromOnlineBookings"):
            self.assertIn(mapped, report["mapped_keys"])
        self.assertNotIn("IMPORT_SUMMARY", json.dumps(report))

    def test_dry_run_distinguishes_null_missing_and_empty_string(self):
        _, report = self.run_dry()
        category = report["fields"]["staffCategoryName"]
        self.assertEqual(category["null"], 1)     # record 1: None
        self.assertEqual(category["missing"], 1)  # record 2: absent
        self.assertEqual(category["empty_string"], 0)
        last = report["fields"]["lastName"]
        self.assertEqual(last["empty_string"], 1)  # record 2: ""
        self.assertEqual(last["missing"], 0)
        self.assertEqual(last["null"], 0)
        first = report["fields"]["firstName"]
        self.assertEqual(first["valued"], 2)
        self.assertEqual(first["inferred_type"], "string")

    def test_normal_import_of_same_fixture_still_works(self):
        out = io.StringIO()
        call_command(
            "import_staff", _write(self.FIXTURE), stdout=out)
        self.assertIn('"created": 2', out.getvalue())
        self.assertEqual(StaffMember.objects.count(), 2)
        self.assertEqual(
            StaffMember.objects.get(external_id="dry-1").display_name,
            "Dry Run")


class ImportStaffPreviewTests(TestCase):
    """Cycle 139: --dry-run import preview twin -- would-create /
    would-update counts, level resolution, landed toggle/active
    state; reads only, writer never entered."""

    PAYLOAD = [
        # row 0: stored member + stored level -> would-update
        {"staffId": "stf-old", "firstName": "New", "lastName": "Name",
         "staffCategoryName": "Artist Level 1",
         "hideFromOnlineBookings": True},
        # row 1: new member + unknown level -> would-create,
        # level unresolved / would-create
        {"staffId": "stf-new", "firstName": "Fresh",
         "staffCategoryName": "Artist Level 9"},
        # row 2: same new level again -> resolves via row 1
        {"staffId": "stf-new2", "firstName": "Also Fresh",
         "staffCategoryName": "Artist Level 9",
         "hideFromOnlineBookings": False},
        # rows 3-4: the writer's two skip reasons
        {"firstName": "No", "lastName": "Id"},
        {"staffId": "stf-noname"},
        # row 5: repeat of row 1's id -> would-update within file,
        # no hide key keeps row 1's previewed toggle (True)
        {"staffId": "stf-new", "firstName": "Fresh Again"},
    ]

    def setUp(self):
        self.salon = Salon.objects.create(name="My Salon")
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Artist Level 1")
        self.old = StaffMember.objects.create(
            salon=self.salon, external_id="stf-old",
            display_name="Old Name", staff_level=self.level,
            online_bookable=True, active=False)

    def run_preview(self, payload=None, **kwargs):
        out = io.StringIO()
        call_command("import_staff", _write(
            self.PAYLOAD if payload is None else payload),
            dry_run=True, stdout=out, **kwargs)
        return json.loads(out.getvalue())

    def test_preview_counts_and_shape_report_kept(self):
        report = self.run_preview()
        self.assertEqual(report["record_count"], 6)
        self.assertIn("staffCategoryName", report["fields"])
        preview = report["import_preview"]
        self.assertTrue(preview["salon_exists"])
        self.assertEqual(preview["would_create"], 2)
        self.assertEqual(preview["would_update"], 2)
        self.assertEqual(preview["would_skip"], 2)
        self.assertEqual(preview["levels_linked"], 3)
        self.assertEqual(preview["levels_resolved"], 2)
        actions = [r["action"] for r in preview["records"]]
        self.assertEqual(actions, [
            "would_update", "would_create", "would_create",
            "would_skip", "would_skip", "would_update"])
        self.assertEqual(preview["records"][3]["reason"],
                         "missing_external_id")
        self.assertEqual(preview["records"][4]["reason"],
                         "missing_display_name")

    def test_preview_unresolved_levels_named_by_row(self):
        preview = self.run_preview()["import_preview"]
        self.assertEqual(preview["unresolved_levels"], [
            {"row": 1, "external_id": "stf-new",
             "level": "Artist Level 9"}])
        self.assertEqual(preview["levels_would_create"],
                         ["Artist Level 9"])
        self.assertTrue(preview["records"][0]["level_resolved"])
        self.assertTrue(preview["records"][2]["level_resolved"])
        self.assertFalse(preview["records"][2]["level_would_create"])

    def test_preview_landed_active_and_booking_toggle(self):
        records = self.run_preview()["import_preview"]["records"]
        # update: active never written (stays False), hide=True
        # lands online_bookable=False
        self.assertFalse(records[0]["active"])
        self.assertFalse(records[0]["online_bookable"])
        # create: model defaults land (active + bookable True)
        self.assertTrue(records[1]["active"])
        self.assertTrue(records[1]["online_bookable"])
        # explicit hide=False lands True; skipped rows land nothing
        self.assertTrue(records[2]["online_bookable"])
        self.assertIsNone(records[3]["active"])
        self.assertIsNone(records[3]["online_bookable"])
        self.assertTrue(records[5]["online_bookable"])

    def test_preview_writes_nothing(self):
        before = (Salon.objects.count(), StaffLevel.objects.count(),
                  StaffMember.objects.count())
        self.run_preview()
        self.assertEqual(before, (
            Salon.objects.count(), StaffLevel.objects.count(),
            StaffMember.objects.count()))
        self.old.refresh_from_db()
        self.assertEqual(self.old.display_name, "Old Name")
        self.assertTrue(self.old.online_bookable)
        self.assertFalse(self.old.active)
        self.assertFalse(StaffMember.objects.filter(
            external_id="stf-new").exists())
        self.assertFalse(StaffLevel.objects.filter(
            name="Artist Level 9").exists())

    def test_preview_missing_salon_would_create_all(self):
        report = self.run_preview(payload=[
            {"staffId": "g-1", "firstName": "Ghost",
             "staffCategoryName": "Level G"}], salon="Ghost Salon")
        preview = report["import_preview"]
        self.assertFalse(preview["salon_exists"])
        self.assertEqual(preview["would_create"], 1)
        self.assertEqual(preview["would_update"], 0)
        self.assertEqual(len(preview["unresolved_levels"]), 1)
        # the lookup must not create the salon it looked for
        self.assertFalse(Salon.objects.filter(
            name="Ghost Salon").exists())
