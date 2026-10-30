import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.services import (
    bookable_slots,
    create_online_booking,
    reschedule_online_booking,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class OnlineBookingBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.online_staff = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist", online_bookable=True
        )
        self.offline_staff = StaffMember.objects.create(
            salon=self.salon, display_name="Offline Stylist", online_bookable=False
        )
        self.unrostered_staff = StaffMember.objects.create(
            salon=self.salon, display_name="Unrostered Stylist", online_bookable=True
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        for staff in (self.online_staff, self.offline_staff):
            RosterPattern.objects.create(
                staff_member=staff, weekday=0,
                start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
            )

    def _book(self, staff=None, hour=10, **kw):
        kw.setdefault("client", self.client)
        kw.setdefault("staff_member", staff or self.online_staff)
        kw.setdefault("service", self.service)
        kw.setdefault("start", at(MONDAY, hour))
        return create_online_booking(**kw)


class BookableSlotsTests(OnlineBookingBase):
    def test_toggle_on_staff_offered_with_rostered_interval(self):
        result = bookable_slots(self.salon, self.service, MONDAY)
        self.assertEqual([r.staff_member for r in result], [self.online_staff])
        self.assertEqual(
            [(i.start, i.end) for i in result[0].intervals],
            [(at(MONDAY, 9), at(MONDAY, 17))],
        )

    def test_toggle_off_staff_never_appear(self):
        result = bookable_slots(self.salon, self.service, MONDAY)
        self.assertNotIn(self.offline_staff, [r.staff_member for r in result])
        self.assertTrue(all(r.online_bookable for r in result))

    def test_unrostered_time_is_never_offered(self):
        # Unrostered (but toggle-on) staff get no entry at all.
        result = bookable_slots(self.salon, self.service, MONDAY)
        self.assertNotIn(self.unrostered_staff, [r.staff_member for r in result])
        # A weekday nobody is rostered on offers nothing.
        tuesday = MONDAY + datetime.timedelta(days=1)
        self.assertEqual(bookable_slots(self.salon, self.service, tuesday), [])

    def test_existing_appointment_is_subtracted_from_slots(self):
        self._book(hour=11)
        result = bookable_slots(self.salon, self.service, MONDAY)
        self.assertEqual(
            [(i.start, i.end) for i in result[0].intervals],
            [(at(MONDAY, 9), at(MONDAY, 11)), (at(MONDAY, 11, 45), at(MONDAY, 17))],
        )


class CreateOnlineBookingTests(OnlineBookingBase):
    def test_toggle_on_staff_book_successfully(self):
        appt = self._book()
        self.assertEqual(appt.status, Appointment.Status.BOOKED)
        self.assertEqual(appt.end, at(MONDAY, 10, 45))
        self.assertEqual(appt.staff_member, self.online_staff)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_toggle_off_staff_cannot_be_booked(self):
        with self.assertRaises(ValidationError):
            self._book(staff=self.offline_staff)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_unrostered_time_cannot_be_booked(self):
        with self.assertRaises(ValidationError):
            self._book(hour=18)
        with self.assertRaises(ValidationError):
            self._book(staff=self.unrostered_staff)
        self.assertEqual(Appointment.objects.count(), 0)


class RescheduleOnlineBookingTests(OnlineBookingBase):
    def test_reschedule_to_available_slot_succeeds(self):
        appt = self._book(hour=10)
        moved = reschedule_online_booking(appt, at(MONDAY, 13))
        self.assertEqual(moved.pk, appt.pk)
        self.assertEqual(moved.start, at(MONDAY, 13))
        # Original 45-minute duration is preserved.
        self.assertEqual(moved.end, at(MONDAY, 13, 45))
        self.assertEqual(moved.status, Appointment.Status.BOOKED)
        appt.refresh_from_db()
        self.assertEqual(appt.start, at(MONDAY, 13))

    def test_reschedule_to_unavailable_slot_is_refused(self):
        appt = self._book(hour=10)
        self._book(hour=13)  # occupies 13:00-13:45 for the same staff
        # Outside the 09:00-17:00 roster window.
        with self.assertRaises(ValidationError):
            reschedule_online_booking(appt, at(MONDAY, 18))
        # Overlapping the other appointment.
        with self.assertRaises(ValidationError):
            reschedule_online_booking(appt, at(MONDAY, 13))
        appt.refresh_from_db()
        self.assertEqual(appt.start, at(MONDAY, 10))
        self.assertEqual(appt.end, at(MONDAY, 10, 45))

    def test_reschedule_with_toggle_off_is_refused(self):
        appt = self._book(hour=10)
        # Toggle turned off after the appointment was booked online.
        self.online_staff.online_bookable = False
        self.online_staff.save(update_fields=["online_bookable"])
        with self.assertRaises(ValidationError):
            reschedule_online_booking(appt, at(MONDAY, 13))
        appt.refresh_from_db()
        self.assertEqual(appt.start, at(MONDAY, 10))
        self.assertEqual(appt.end, at(MONDAY, 10, 45))
