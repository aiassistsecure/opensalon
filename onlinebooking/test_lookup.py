import datetime

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.lookup import next_online_booking, upcoming_online_bookings
from onlinebooking.services import create_online_booking
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)  # a Monday


def at(day_offset, hour, minute=0):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12, minutes=minute)


class LookupBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist", online_bookable=True
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        self.other_client = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )

    def _appt(self, start, client=None, staff=None, service=None, **kw):
        return Appointment.objects.create(
            client=client or self.client,
            staff_member=staff or self.staff,
            service=service or self.service,
            start=start,
            end=start + datetime.timedelta(minutes=45),
            **kw,
        )

    def _lookup(self, salon=None, client=None, now=NOW):
        return upcoming_online_bookings(
            salon or self.salon, client or self.client, now=now
        )


class UpcomingOnlineBookingsTests(LookupBase):
    def test_future_only_and_exactly_now_counts_as_upcoming(self):
        self._appt(at(-1, 9))
        self._appt(NOW - datetime.timedelta(minutes=1))
        at_now = self._appt(NOW)
        future = self._appt(at(1, 9))
        self.assertEqual(list(self._lookup()), [at_now, future])

    def test_ordered_soonest_first_with_pk_tie_break(self):
        later = self._appt(at(5, 9))
        first_same = self._appt(at(1, 9))
        second_same = self._appt(at(1, 9))
        sooner = self._appt(at(0, 13))
        self.assertEqual(
            list(self._lookup()), [sooner, first_same, second_same, later]
        )

    def test_only_booked_and_confirmed_are_upcoming(self):
        booked = self._appt(at(1, 9), status=Appointment.Status.BOOKED)
        confirmed = self._appt(at(1, 10), status=Appointment.Status.CONFIRMED)
        for status in (
            Appointment.Status.CANCELLED,
            Appointment.Status.COMPLETED,
            Appointment.Status.NO_SHOW,
            Appointment.Status.ARRIVED,
            Appointment.Status.IN_SERVICE,
        ):
            self._appt(at(2, 9), status=status)
        self.assertEqual(list(self._lookup()), [booked, confirmed])

    def test_never_returns_another_clients_bookings(self):
        mine = self._appt(at(1, 9))
        self._appt(at(1, 10), client=self.other_client)
        self.assertEqual(list(self._lookup()), [mine])

    def test_salon_scoped_client_of_other_salon_gets_nothing(self):
        outsider = Client.objects.create(
            salon=self.other_salon, first_name="Out", last_name="Sider"
        )
        self._appt(at(1, 9), client=outsider)
        self.assertEqual(list(self._lookup(client=outsider)), [])
        # And querying the other salon never surfaces this salon's book.
        mine = self._appt(at(1, 10))
        self.assertEqual(list(self._lookup(salon=self.other_salon)), [])
        self.assertEqual(list(self._lookup()), [mine])

    def test_cross_salon_staff_or_service_is_excluded(self):
        foreign_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Foreign Stylist"
        )
        foreign_category = ServiceCategory.objects.create(
            salon=self.other_salon, name="Foreign"
        )
        foreign_service = Service.objects.create(
            category=foreign_category, name="Foreign Cut", service_minutes=45
        )
        self._appt(at(1, 9), staff=foreign_staff)
        self._appt(at(1, 10), service=foreign_service)
        mine = self._appt(at(1, 11))
        self.assertEqual(list(self._lookup()), [mine])

    def test_empty_when_no_qualifying_bookings(self):
        self._appt(at(1, 9), client=self.other_client)
        self._appt(at(-1, 9))
        self.assertEqual(list(self._lookup()), [])
        self.assertEqual(list(self._lookup(client=self.other_client, now=at(2, 9))), [])

    def test_default_now_uses_current_time(self):
        past = self._appt(datetime.datetime(2000, 1, 1, 9, tzinfo=UTC))
        future = self._appt(datetime.datetime(2100, 1, 1, 9, tzinfo=UTC))
        result = upcoming_online_bookings(self.salon, self.client)
        self.assertEqual(list(result), [future])
        self.assertNotIn(past, result)

    def test_none_salon_or_client_returns_empty(self):
        self._appt(at(1, 9))
        self.assertEqual(
            list(upcoming_online_bookings(None, self.client, now=NOW)), []
        )
        self.assertEqual(
            list(upcoming_online_bookings(self.salon, None, now=NOW)), []
        )

    def test_booking_created_online_is_found_by_lookup(self):
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
        )
        monday = NOW.date() + datetime.timedelta(days=7)  # next Monday
        start = datetime.datetime.combine(
            monday, datetime.time(10, 0), tzinfo=UTC
        )
        appt = create_online_booking(
            client=self.client, staff_member=self.staff,
            service=self.service, start=start,
        )
        self.assertEqual(list(self._lookup()), [appt])


class NextOnlineBookingTests(LookupBase):
    def test_returns_soonest_upcoming_booking(self):
        self._appt(at(5, 9))
        sooner = self._appt(at(1, 9))
        self._appt(at(-1, 9))
        self.assertEqual(next_online_booking(self.salon, self.client, now=NOW), sooner)

    def test_returns_none_when_nothing_upcoming(self):
        self._appt(at(-1, 9))
        self._appt(at(1, 9), status=Appointment.Status.CANCELLED)
        self.assertIsNone(next_online_booking(self.salon, self.client, now=NOW))
        self.assertIsNone(
            next_online_booking(self.other_salon, self.client, now=NOW)
        )
