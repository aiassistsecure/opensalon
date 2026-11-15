"""Tests for import_roster_derived: bands from the real book."""

import datetime
import io
import json

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember


class ImportRosterDerivedTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Mint On The Avenue", timezone="America/New_York"
        )
        self.member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon
        )
        category = ServiceCategory.objects.create(name="Hair", salon=self.salon)
        self.service = Service.objects.create(
            name="Women's Haircut", category=category, service_minutes=60
        )
        self.person = Client.objects.create(
            salon=self.salon, first_name="Jaime", last_name="Orta"
        )

    def _book(self, day, start_utc_hour, end_utc_hour):
        start = datetime.datetime.combine(
            day, datetime.time(start_utc_hour, 0), tzinfo=datetime.timezone.utc
        )
        end = datetime.datetime.combine(
            day, datetime.time(end_utc_hour, 0), tzinfo=datetime.timezone.utc
        )
        return Appointment.objects.create(
            client=self.person,
            staff_member=self.member,
            service=self.service,
            start=start,
            end=end,
            status=Appointment.Status.CONFIRMED,
        )

    def test_bands_derive_from_history_and_rerun_is_idempotent(self):
        mondays = [datetime.date(2026, 9, 7) + datetime.timedelta(weeks=i) for i in range(5)]
        wednesdays = [datetime.date(2026, 9, 9) + datetime.timedelta(weeks=i) for i in range(5)]
        for day in mondays:  # 13:00-17:00 UTC = 9 AM - 1 PM New York
            self._book(day, 13, 17)
        for day in wednesdays:  # 14:00-18:00 UTC = 10 AM - 2 PM New York
            self._book(day, 14, 18)
        call_command("import_roster_derived")
        patterns = {
            p.weekday: p for p in RosterPattern.objects.filter(staff_member=self.member)
        }
        self.assertEqual(set(patterns), {0, 2})
        self.assertEqual(patterns[0].start_time, datetime.time(9, 0))
        self.assertEqual(patterns[0].end_time, datetime.time(13, 0))
        self.assertEqual(patterns[2].start_time, datetime.time(10, 0))
        self.assertEqual(patterns[2].end_time, datetime.time(14, 0))
        call_command("import_roster_derived")
        self.assertEqual(RosterPattern.objects.filter(staff_member=self.member).count(), 2)

    def test_thin_history_proposes_nothing(self):
        for i in range(2):  # only two Tuesdays — below --min-days 4
            self._book(datetime.date(2026, 9, 8) + datetime.timedelta(weeks=i), 13, 17)
        call_command("import_roster_derived")
        self.assertEqual(RosterPattern.objects.count(), 0)


class ImportRosterDerivedSalonIdTests(TestCase):
    """--salon-id bridge: id selects the salon, beats --salon,
    and a nonexistent id raises CommandError with no writes."""

    def setUp(self):
        self.salon = Salon.objects.create(
            name="Target Salon", timezone="America/New_York")
        self.other = Salon.objects.create(
            name="Other Salon", timezone="America/New_York")
        category = ServiceCategory.objects.create(name="Hair", salon=self.salon)
        self.service = Service.objects.create(
            name="Cut", category=category, service_minutes=60)
        self.person = Client.objects.create(
            salon=self.salon, first_name="Jaime", last_name="Orta")
        self.member = StaffMember.objects.create(
            display_name="Target Member", salon=self.salon)
        self.other_member = StaffMember.objects.create(
            display_name="Other Member", salon=self.other)

    def _book(self, member, day):
        start = datetime.datetime.combine(
            day, datetime.time(13, 0), tzinfo=datetime.timezone.utc)
        end = datetime.datetime.combine(
            day, datetime.time(17, 0), tzinfo=datetime.timezone.utc)
        return Appointment.objects.create(
            client=self.person, staff_member=member,
            service=self.service, start=start, end=end,
            status=Appointment.Status.CONFIRMED)

    def _seed(self):
        mondays = [datetime.date(2026, 9, 7) + datetime.timedelta(weeks=i)
                   for i in range(5)]
        for day in mondays:
            self._book(self.member, day)
            self._book(self.other_member, day)

    def test_salon_id_selects_existing_salon(self):
        self._seed()
        out = io.StringIO()
        # CLI form proves the --salon-id argument is wired.
        call_command("import_roster_derived",
                     "--salon-id", str(self.salon.pk), stdout=out)
        self.assertIn("salons=1", out.getvalue())
        self.assertEqual(RosterPattern.objects.filter(
            staff_member=self.member).count(), 1)
        self.assertEqual(RosterPattern.objects.filter(
            staff_member=self.other_member).count(), 0)

    def test_salon_id_nonexistent_raises_and_writes_nothing(self):
        self._seed()
        with self.assertRaises(CommandError):
            call_command("import_roster_derived", salon_id=999999)
        self.assertEqual(RosterPattern.objects.count(), 0)

    def test_salon_id_takes_precedence_over_salon_name(self):
        self._seed()
        call_command("import_roster_derived", salon_id=self.salon.pk,
                     salon="Other Salon")
        self.assertEqual(RosterPattern.objects.filter(
            staff_member=self.member).count(), 1)
        self.assertEqual(RosterPattern.objects.filter(
            staff_member=self.other_member).count(), 0)


class ImportRosterDerivedSummaryTests(TestCase):
    """IMPORT_SUMMARY line: parses as JSON with the plain-line totals."""

    def setUp(self):
        self.salon = Salon.objects.create(
            name="Mint On The Avenue", timezone="America/New_York")
        self.member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon)
        category = ServiceCategory.objects.create(name="Hair", salon=self.salon)
        self.service = Service.objects.create(
            name="Women's Haircut", category=category, service_minutes=60)
        self.person = Client.objects.create(
            salon=self.salon, first_name="Jaime", last_name="Orta")
        mondays = [datetime.date(2026, 9, 7) + datetime.timedelta(weeks=i)
                   for i in range(5)]
        wednesdays = [datetime.date(2026, 9, 9) + datetime.timedelta(weeks=i)
                      for i in range(5)]
        for day in mondays:
            self._book(day, 13, 17)
        for day in wednesdays:
            self._book(day, 14, 18)

    def _book(self, day, start_utc_hour, end_utc_hour):
        start = datetime.datetime.combine(
            day, datetime.time(start_utc_hour, 0),
            tzinfo=datetime.timezone.utc)
        end = datetime.datetime.combine(
            day, datetime.time(end_utc_hour, 0),
            tzinfo=datetime.timezone.utc)
        return Appointment.objects.create(
            client=self.person, staff_member=self.member,
            service=self.service, start=start, end=end,
            status=Appointment.Status.CONFIRMED)

    def _summary(self, out):
        lines = [ln for ln in out.splitlines()
                 if ln.startswith("IMPORT_SUMMARY ")]
        self.assertEqual(len(lines), 1)
        return json.loads(lines[0][len("IMPORT_SUMMARY "):])

    def test_real_run_import_summary(self):
        out = io.StringIO()
        call_command("import_roster_derived", stdout=out)
        text = out.getvalue()
        self.assertIn(
            "import_roster_derived: salons=1 members=1 created=2 "
            "existing=0 skipped_bands=0", text)
        self.assertEqual(self._summary(text), {
            "salons": 1, "members": 1, "created": 2,
            "existing": 0, "skipped_bands": 0})

    def test_dry_run_import_summary_uses_would_create(self):
        out = io.StringIO()
        call_command("import_roster_derived", dry_run=True, stdout=out)
        text = out.getvalue()
        self.assertEqual(RosterPattern.objects.count(), 0)
        self.assertIn("would_create=2", text)
        summary = self._summary(text)
        self.assertEqual(summary, {
            "salons": 1, "members": 1, "would_create": 2,
            "existing": 0, "skipped_bands": 0})
        self.assertNotIn("created", summary)
