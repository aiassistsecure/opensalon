"""--format text|json for repair_staff_levels.

Pins that text output is byte-identical to the historical
output, that json mode prints exactly one JSON object carrying
the same facts (salon, merged / renamed / unassigned /
conflicts counts, and ``dry_run``), and that an invalid format
is rejected. Fixtures are tiny synthetic records -- unit logic
only.
"""
import io
import json
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from saloncore.models import (
    Salon, Service, ServiceCategory, ServicePrice, StaffLevel,
)
from team.models import StaffMember

CAT_ID = "RqYB0nJ02216iNO36VAwzA"  # Artist Level 6's category id
UNKNOWN_ID = "H4zBPQ63XrW87rOtEvXClA"

EXPECTED_TEXT = (
    "repair_staff_levels: salon=Mint merged=1 renamed=0 "
    "unassigned=1 conflicts=0\n"
)
EXPECTED_PAYLOAD = {
    "salon": "Mint", "merged": 1, "renamed": 0,
    "unassigned": 1, "conflicts": 0, "dry_run": False,
}


class RepairStaffLevelsFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Mint", timezone="America/New_York")
        self.named = StaffLevel.objects.create(
            salon=self.salon, name="Artist Level 6")
        self.guid = StaffLevel.objects.create(salon=self.salon, name=CAT_ID)
        self.unknown = StaffLevel.objects.create(
            salon=self.salon, name=UNKNOWN_ID)
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Women's Haircut", service_minutes=60)
        ServicePrice.objects.create(
            service=self.service, staff_level=self.guid,
            amount=Decimal("65.00"))
        ServicePrice.objects.create(
            service=self.service, staff_level=self.unknown,
            amount=Decimal("70.00"))
        self.member = StaffMember.objects.create(
            salon=self.salon, display_name="Dawn Davalos",
            staff_level=self.guid)
        staff_file = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False)
        json.dump([{
            "staffCategoryId": CAT_ID,
            "staffCategoryName": "Artist Level 6",
        }], staff_file)
        staff_file.close()
        self.staff_path = staff_file.name

    def _run(self, **kwargs):
        out = io.StringIO()
        call_command("repair_staff_levels", staff=self.staff_path,
                     salon="Mint", stdout=out, **kwargs)
        return out.getvalue()

    def test_default_text_unchanged(self):
        self.assertEqual(self._run(), EXPECTED_TEXT)
        self.assertFalse(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())

    def test_explicit_text_matches_default(self):
        self.assertEqual(self._run(format="text"), EXPECTED_TEXT)
        self.assertFalse(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())

    def test_json_output_parses_and_carries_facts(self):
        text = self._run(format="json")
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertNotIn("repair_staff_levels:", text)
        self.assertEqual(json.loads(text), EXPECTED_PAYLOAD)
        self.assertFalse(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())
        price = ServicePrice.objects.get(
            service=self.service, staff_level=self.named)
        self.assertEqual(price.amount, Decimal("65.00"))
        self.member.refresh_from_db()
        self.assertEqual(self.member.staff_level, self.named)
        self.unknown.refresh_from_db()
        self.assertEqual(self.unknown.name, "Unassigned ····XClA")

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("repair_staff_levels", "--staff", self.staff_path,
                     "--salon", "Mint", "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), EXPECTED_PAYLOAD)
        self.assertFalse(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())

    def test_dry_run_json_reports_dry_run_and_writes_nothing(self):
        text = self._run(dry_run=True, format="json")
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertNotIn("would merge", text)
        self.assertNotIn("would rename", text)
        payload = dict(EXPECTED_PAYLOAD, dry_run=True)
        self.assertEqual(json.loads(text), payload)
        self.assertTrue(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())
        self.unknown.refresh_from_db()
        self.assertEqual(self.unknown.name, UNKNOWN_ID)

    def test_dry_run_text_unchanged(self):
        text = self._run(dry_run=True, format="text")
        self.assertIn(
            f"repair_staff_levels dry-run: would merge level "
            f"'{CAT_ID}' into 'Artist Level 6'", text)
        self.assertIn(
            "repair_staff_levels dry-run: salon=Mint merged=1 "
            "renamed=0 unassigned=1 conflicts=0 "
            "-- no changes written", text)
        self.assertTrue(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())

    def test_invalid_format_rejected(self):
        with self.assertRaises(CommandError):
            self._run(format="bogus")
        self.assertTrue(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())
        self.unknown.refresh_from_db()
        self.assertEqual(self.unknown.name, UNKNOWN_ID)

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("repair_staff_levels", "--staff", self.staff_path,
                         "--salon", "Mint", "--format", "bogus",
                         stdout=io.StringIO())
        self.assertTrue(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())
