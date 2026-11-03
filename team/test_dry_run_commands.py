"""Tests for --dry-run on check_in, check_out, seed_staff_services
and import_roster_derived: dry runs write nothing, preview counts
match what a real run then does, and real behaviour is unchanged.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import (
    Salon, Service, ServiceCategory, ServicePrice, StaffLevel,
)
from team.availability import check_in
from team.models import (
    AttendanceRecord, RosterPattern, StaffMember, StaffService,
)

AT = datetime.datetime(2026, 11, 2, 9, 0, tzinfo=datetime.timezone.utc)
OUT = datetime.datetime(2026, 11, 2, 17, 0, tzinfo=datetime.timezone.utc)


def _run(name, **kwargs):
    out = io.StringIO()
    call_command(name, stdout=out, **kwargs)
    return out.getvalue()


class CheckInDryRunTests(TestCase):
    def setUp(self):
        salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=salon, display_name="Stylist One")

    def test_dry_run_previews_record_and_writes_nothing(self):
        out = _run("check_in", staff_member_id=self.staff.pk,
                   at=AT.isoformat(), note="On time", dry_run=True)
        self.assertEqual(AttendanceRecord.objects.count(), 0)
        self.assertFalse(self.staff.is_checked_in())
        self.assertIn("Dry run: would create AttendanceRecord", out)
        self.assertIn("event_type=check_in", out)
        self.assertIn(f"staff_member_id={self.staff.pk}", out)
        self.assertIn(str(AT), out)
        self.assertIn("'On time'", out)

    def test_dry_run_via_cli_then_real_run_unchanged(self):
        out = io.StringIO()
        call_command("check_in", "--staff-member-id", str(self.staff.pk),
                     "--at", AT.isoformat(), "--dry-run", stdout=out)
        self.assertEqual(AttendanceRecord.objects.count(), 0)
        _run("check_in", staff_member_id=self.staff.pk, at=AT.isoformat())
        self.assertEqual(AttendanceRecord.objects.count(), 1)
        self.assertTrue(self.staff.is_checked_in())

    def test_dry_run_when_already_checked_in_is_error(self):
        check_in(self.staff, recorded_at=AT)
        with self.assertRaises(CommandError):
            _run("check_in", staff_member_id=self.staff.pk,
                 at=AT.isoformat(), dry_run=True)
        self.assertEqual(AttendanceRecord.objects.count(), 1)


class CheckOutDryRunTests(TestCase):
    def setUp(self):
        salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=salon, display_name="Stylist One")
        check_in(self.staff, recorded_at=AT)

    def test_dry_run_previews_record_and_writes_nothing(self):
        out = _run("check_out", staff_member_id=self.staff.pk,
                   at=OUT.isoformat(), note="Done", dry_run=True)
        self.assertEqual(
            AttendanceRecord.objects.filter(
                event_type=AttendanceRecord.EventType.CHECK_OUT).count(), 0)
        self.assertTrue(self.staff.is_checked_in())
        self.assertIn("event_type=check_out", out)
        self.assertIn(str(OUT), out)
        self.assertIn("'Done'", out)

    def test_dry_run_when_not_checked_in_is_error(self):
        _run("check_out", staff_member_id=self.staff.pk, at=OUT.isoformat())
        with self.assertRaises(CommandError):
            _run("check_out", staff_member_id=self.staff.pk,
                 at=OUT.isoformat(), dry_run=True)
        self.assertEqual(AttendanceRecord.objects.count(), 2)


class SeedStaffServicesDryRunTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Cap Salon", timezone="UTC")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Color")
        level_a = StaffLevel.objects.create(salon=self.salon, name="Level A")
        level_b = StaffLevel.objects.create(salon=self.salon, name="Level B")
        self.ana = StaffMember.objects.create(
            salon=self.salon, display_name="Ana", staff_level=level_a)
        self.bea = StaffMember.objects.create(
            salon=self.salon, display_name="Bea", staff_level=level_b)
        self.cut = Service.objects.create(
            category=cat, name="Full Color", service_minutes=90)
        Service.objects.create(category=cat, name="Gloss", service_minutes=30)
        ServicePrice.objects.create(
            service=self.cut, staff_level=level_a, amount=Decimal("80.00"))

    def test_dry_run_counts_by_member_and_writes_nothing(self):
        out = _run("seed_staff_services", dry_run=True)
        self.assertEqual(StaffService.objects.count(), 0)
        # Ana: cut enabled + gloss enabled; Bea: cut off + gloss on.
        self.assertIn(
            f"staff_member_id={self.ana.pk} would_create=2 would_enable=2",
            out)
        self.assertIn(
            f"staff_member_id={self.bea.pk} would_create=2 would_enable=1",
            out)
        self.assertIn("would_create=4 would_enable=3", out)

    def test_dry_run_counts_match_real_run_and_skip_existing(self):
        StaffService.objects.create(
            staff_member=self.ana, service=self.cut, enabled=True)
        out = _run("seed_staff_services", dry_run=True)
        self.assertEqual(StaffService.objects.count(), 1)
        self.assertIn("would_create=3 would_enable=2", out)
        _run("seed_staff_services")
        self.assertEqual(StaffService.objects.count(), 4)


class ImportRosterDerivedDryRunTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Mint On The Avenue", timezone="America/New_York")
        self.member = StaffMember.objects.create(
            display_name="Member One", salon=self.salon)
        self.other = StaffMember.objects.create(
            display_name="Member Two", salon=self.salon)
        cat = ServiceCategory.objects.create(name="Hair", salon=self.salon)
        self.service = Service.objects.create(
            name="Cut", category=cat, service_minutes=60)
        self.person = Client.objects.create(
            salon=self.salon, first_name="Jaime", last_name="Orta")

    def _book(self, member, day, start_h, end_h):
        tz = datetime.timezone.utc
        Appointment.objects.create(
            client=self.person, staff_member=member, service=self.service,
            start=datetime.datetime.combine(day, datetime.time(start_h), tzinfo=tz),
            end=datetime.datetime.combine(day, datetime.time(end_h), tzinfo=tz),
            status=Appointment.Status.CONFIRMED)

    def _seed_history(self):
        mondays = [datetime.date(2026, 9, 7) + datetime.timedelta(weeks=i)
                   for i in range(5)]
        wednesdays = [datetime.date(2026, 9, 9) + datetime.timedelta(weeks=i)
                      for i in range(5)]
        for day in mondays:
            self._book(self.member, day, 13, 17)
            self._book(self.other, day, 13, 17)
        for day in wednesdays:
            self._book(self.member, day, 14, 18)

    def test_dry_run_counts_by_member_weekday_and_writes_nothing(self):
        self._seed_history()
        out = _run("import_roster_derived", dry_run=True)
        self.assertEqual(RosterPattern.objects.count(), 0)
        self.assertIn(
            f"staff_member_id={self.member.pk} weekday=0 "
            f"would_create=1 existing=0", out)
        self.assertIn(
            f"staff_member_id={self.member.pk} weekday=2 "
            f"would_create=1 existing=0", out)
        self.assertIn(
            f"staff_member_id={self.other.pk} weekday=0 "
            f"would_create=1 existing=0", out)
        self.assertIn("would_create=3", out)

    def test_dry_run_after_real_run_counts_existing(self):
        self._seed_history()
        _run("import_roster_derived")
        self.assertEqual(RosterPattern.objects.count(), 3)
        out = _run("import_roster_derived", dry_run=True)
        self.assertEqual(RosterPattern.objects.count(), 3)
        self.assertIn("would_create=0", out)
        self.assertIn("existing=3", out)
