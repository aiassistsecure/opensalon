"""--dry-run for repair_staff_levels: preview writes nothing,
preview counts match the real run, real behaviour is unchanged.
Fixtures are tiny synthetic records -- unit logic only.
"""
import io
import json
import re
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from saloncore.models import (
    Salon, Service, ServiceCategory, ServicePrice, StaffLevel,
)
from team.models import StaffMember

CAT_ID = "RqYB0nJ02216iNO36VAwzA"  # Artist Level 6's category id
UNKNOWN_ID = "H4zBPQ63XrW87rOtEvXClA"
CONFLICT_ID = "AbCdEfGhIjKlMnOpQrStUv"
NO_TWIN_ID = "ZyXwVuTsRqPoNmLkJiHgFe"

_COUNTS = re.compile(
    r"merged=(\d+) renamed=(\d+) unassigned=(\d+) conflicts=(\d+)")


def _counts(text):
    match = _COUNTS.search(text)
    assert match is not None, text
    return tuple(int(group) for group in match.groups())


def _staff_file(rows):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(rows, handle)
    handle.close()
    return handle.name


def _snapshot():
    return (
        sorted(StaffLevel.objects.values_list("pk", "name")),
        sorted(ServicePrice.objects.values_list(
            "pk", "service_id", "staff_level_id", "amount")),
        sorted(StaffMember.objects.values_list("pk", "staff_level_id")),
    )


class RepairStaffLevelsDryRunTests(TestCase):
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
        self.staff_path = _staff_file([{
            "staffCategoryId": CAT_ID,
            "staffCategoryName": "Artist Level 6",
        }])

    def _run(self, **kwargs):
        out = io.StringIO()
        call_command("repair_staff_levels", staff=self.staff_path,
                     salon="Mint", stdout=out, **kwargs)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        before = _snapshot()
        out = self._run(dry_run=True)
        self.assertEqual(_snapshot(), before)
        self.assertIn("would merge", out)
        self.assertIn(
            f"would rename level '{UNKNOWN_ID}' to "
            f"'Unassigned ····XClA'", out)
        self.assertIn("-- no changes written", out)

    def test_dry_run_counts_match_real_run(self):
        dry = self._run(dry_run=True)
        self.assertEqual(_counts(dry), (1, 0, 1, 0))
        real = self._run()
        self.assertEqual(_counts(real), _counts(dry))

    def test_dry_run_via_cli_flag_then_real_behaviour_unchanged(self):
        out = io.StringIO()
        call_command("repair_staff_levels", "--staff", self.staff_path,
                     "--salon", "Mint", "--dry-run", stdout=out)
        self.assertTrue(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())
        self._run()
        self.assertFalse(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())
        price = ServicePrice.objects.get(
            service=self.service, staff_level=self.named)
        self.assertEqual(price.amount, Decimal("65.00"))
        self.member.refresh_from_db()
        self.assertEqual(self.member.staff_level, self.named)
        self.unknown.refresh_from_db()
        self.assertEqual(self.unknown.name, "Unassigned ····XClA")


class RepairRenameAndConflictDryRunTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Mint", timezone="America/New_York")
        self.named = StaffLevel.objects.create(
            salon=self.salon, name="Artist Level 6")
        self.conflict = StaffLevel.objects.create(
            salon=self.salon, name=CONFLICT_ID)
        self.no_twin = StaffLevel.objects.create(
            salon=self.salon, name=NO_TWIN_ID)
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Women's Haircut", service_minutes=60)
        ServicePrice.objects.create(
            service=self.service, staff_level=self.named,
            amount=Decimal("100.00"))
        ServicePrice.objects.create(
            service=self.service, staff_level=self.conflict,
            amount=Decimal("90.00"))
        self.staff_path = _staff_file([
            {"staffCategoryId": CONFLICT_ID,
             "staffCategoryName": "Artist Level 6"},
            {"staffCategoryId": NO_TWIN_ID,
             "staffCategoryName": "Artist Level 8"},
        ])

    def _run(self, **kwargs):
        out = io.StringIO()
        call_command("repair_staff_levels", staff=self.staff_path,
                     salon="Mint", stdout=out, **kwargs)
        return out.getvalue()

    def test_dry_run_writes_nothing_and_previews_both_paths(self):
        before = _snapshot()
        out = self._run(dry_run=True)
        self.assertEqual(_snapshot(), before)
        self.assertIn("CONFLICT Artist Level 6: 1 price(s) differ", out)
        self.assertIn(
            "would rename level '" + NO_TWIN_ID + "' to "
            "'Artist Level 8'", out)

    def test_preview_counts_match_real_run_and_real_run_unchanged(self):
        dry = self._run(dry_run=True)
        self.assertEqual(_counts(dry), (0, 1, 0, 1))
        real = self._run()
        self.assertEqual(_counts(real), _counts(dry))
        self.conflict.refresh_from_db()
        self.assertEqual(
            self.conflict.name, "Artist Level 6 (duplicate — review)")
        self.no_twin.refresh_from_db()
        self.assertEqual(self.no_twin.name, "Artist Level 8")
