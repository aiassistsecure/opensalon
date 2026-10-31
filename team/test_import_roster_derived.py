"""Tests for import_roster_derived: bands from the real book."""

import datetime

from django.core.management import call_command
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
