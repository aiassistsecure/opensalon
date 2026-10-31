"""The roster resolution: instance rules its date, pattern forever.

team.availability.roster_availability is the resolver both books and
online booking read. A ShiftOverride replaces the member's perpetual
RosterPattern windows on its one date — a placed shift, or a full
day off. Every other date follows the pattern, forever.
"""
import datetime

from django.test import TestCase

from saloncore.models import Salon
from team.availability import roster_availability
from team.models import RosterPattern, ShiftOverride, StaffMember

SAT = datetime.date(2026, 10, 31)  # a Saturday
NEXT_SAT = datetime.date(2026, 11, 7)


class RosterResolutionTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint", timezone="America/New_York")
        self.member = StaffMember.objects.create(
            salon=self.salon, display_name="Dawn Davalos"
        )
        RosterPattern.objects.create(
            staff_member=self.member, weekday=5,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
        )

    def hours(self, day):
        result = roster_availability(self.member, day)
        return [
            (i.start.strftime("%H:%M"), i.end.strftime("%H:%M"))
            for i in result.intervals
        ]

    def test_pattern_rules_without_override(self):
        self.assertEqual(self.hours(SAT), [("09:00", "17:00")])
        self.assertEqual(self.hours(NEXT_SAT), [("09:00", "17:00")])

    def test_instance_shift_replaces_pattern_for_that_date_only(self):
        ShiftOverride.objects.create(
            staff_member=self.member, date=SAT,
            start_time=datetime.time(10, 0), end_time=datetime.time(14, 0),
        )
        self.assertEqual(self.hours(SAT), [("10:00", "14:00")])
        self.assertEqual(self.hours(NEXT_SAT), [("09:00", "17:00")])

    def test_instance_off_empties_that_date_only(self):
        ShiftOverride.objects.create(
            staff_member=self.member, date=SAT, is_off=True
        )
        self.assertEqual(self.hours(SAT), [])
        self.assertEqual(self.hours(NEXT_SAT), [("09:00", "17:00")])

    def test_instance_can_add_a_day_the_pattern_never_had(self):
        sunday = datetime.date(2026, 11, 1)
        self.assertEqual(self.hours(sunday), [])
        ShiftOverride.objects.create(
            staff_member=self.member, date=sunday,
            start_time=datetime.time(11, 0), end_time=datetime.time(15, 0),
        )
        self.assertEqual(self.hours(sunday), [("11:00", "15:00")])


class OnlineBookingFollowsTheResolutionTests(TestCase):
    """available_slots (bookings) must obey the same resolution."""

    def setUp(self):
        from bookings.availability import available_slots

        self.available_slots = available_slots
        self.salon = Salon.objects.create(name="Mint", timezone="America/New_York")
        self.member = StaffMember.objects.create(
            salon=self.salon, display_name="Dawn Davalos"
        )
        RosterPattern.objects.create(
            staff_member=self.member, weekday=5,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
        )

    def staff_ids(self, day):
        return {r.staff_member_id for r in self.available_slots(self.salon, day)}

    def test_off_instance_removes_the_member_that_day_only(self):
        self.assertIn(self.member.pk, self.staff_ids(SAT))
        ShiftOverride.objects.create(
            staff_member=self.member, date=SAT, is_off=True
        )
        self.assertNotIn(self.member.pk, self.staff_ids(SAT))
        self.assertIn(self.member.pk, self.staff_ids(NEXT_SAT))
