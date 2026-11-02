"""Capability enforcement at the booking doors.

Availability with a service offers only the staff who perform it;
the lifecycle write path (create + reschedule) refuses a booking
onto a non-performer. The desk's overlap freedom is untouched —
capability is a different law, and it binds every door.
"""

import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from bookings.availability import available_slots
from bookings.lifecycle import create_appointment, reschedule_appointment
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC
    )


class CapabilityEnforcementTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Door Salon", timezone="UTC")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Senior")
        self.other_level = StaffLevel.objects.create(
            salon=self.salon, name="Junior"
        )
        self.performs = StaffMember.objects.create(
            salon=self.salon, display_name="Performs", staff_level=self.level
        )
        self.does_not = StaffMember.objects.create(
            salon=self.salon, display_name="Does Not",
            staff_level=self.other_level,
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Guest"
        )
        self.service = Service.objects.create(
            category=category, name="Full Color", service_minutes=60
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("90.00"),
        )
        for member in (self.performs, self.does_not):
            RosterPattern.objects.create(
                staff_member=member, weekday=0,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(17, 0),
            )

    def test_slots_offer_only_performers_for_the_service(self):
        result = available_slots(self.salon, MONDAY, service=self.service)
        names = [entry.staff_member.display_name for entry in result]
        self.assertEqual(names, ["Performs"])

    def test_slots_without_a_service_offer_everyone_rostered(self):
        result = available_slots(self.salon, MONDAY)
        names = [entry.staff_member.display_name for entry in result]
        self.assertEqual(names, ["Does Not", "Performs"])

    def test_create_refuses_a_non_performer(self):
        with self.assertRaises(ValidationError):
            create_appointment(
                client=self.client, staff_member=self.does_not,
                service=self.service, start=at(MONDAY, 10),
            )
        self.assertEqual(Appointment.objects.count(), 0)

    def test_create_allows_a_performer(self):
        appt = create_appointment(
            client=self.client, staff_member=self.performs,
            service=self.service, start=at(MONDAY, 10),
        )
        self.assertEqual(appt.staff_member, self.performs)

    def test_reschedule_onto_a_non_performer_is_refused(self):
        appt = create_appointment(
            client=self.client, staff_member=self.performs,
            service=self.service, start=at(MONDAY, 10),
        )
        with self.assertRaises(ValidationError):
            reschedule_appointment(
                appt, at(MONDAY, 13), new_staff_member=self.does_not
            )
        appt.refresh_from_db()
        self.assertEqual(appt.staff_member, self.performs)
