import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.rebook import rebook_appointment
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

PAST_MONDAY = datetime.date(2026, 10, 26)  # a Monday
MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class RebookTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist", online_bookable=True
        )
        self.offline_staff = StaffMember.objects.create(
            salon=self.salon, display_name="Offline Stylist", online_bookable=False
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        for staff in (self.staff, self.offline_staff):
            RosterPattern.objects.create(
                staff_member=staff, weekday=0,
                start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
            )

    def _source(self, staff=None, **kw):
        kw.setdefault("service", self.service)
        kw.setdefault("status", Appointment.Status.COMPLETED)
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            start=at(PAST_MONDAY, 10),
            end=at(PAST_MONDAY, 10) + datetime.timedelta(minutes=45), **kw,
        )

    def test_happy_path_rebooks_same_client_staff_service(self):
        source = self._source()
        new = rebook_appointment(source.pk, at(MONDAY, 11))
        self.assertNotEqual(new.pk, source.pk)
        self.assertEqual(new.client, self.client)
        self.assertEqual(new.staff_member, self.staff)
        self.assertEqual(new.service, self.service)
        self.assertEqual(new.start, at(MONDAY, 11))
        self.assertEqual(new.end, at(MONDAY, 11, 45))
        self.assertEqual(new.status, Appointment.Status.BOOKED)
        source.refresh_from_db()
        self.assertEqual(source.start, at(PAST_MONDAY, 10))
        self.assertEqual(Appointment.objects.count(), 2)

    def test_happy_path_accepts_appointment_instance(self):
        source = self._source()
        new = rebook_appointment(source, at(MONDAY, 13))
        self.assertEqual(new.start, at(MONDAY, 13))

    def test_toggle_off_refusal_creates_nothing(self):
        source = self._source(staff=self.offline_staff)
        with self.assertRaises(ValidationError):
            rebook_appointment(source.pk, at(MONDAY, 11))
        self.assertEqual(Appointment.objects.count(), 1)

    def test_toggle_turned_off_since_original_refused(self):
        source = self._source()
        self.staff.online_bookable = False
        self.staff.save(update_fields=["online_bookable"])
        with self.assertRaises(ValidationError):
            rebook_appointment(source, at(MONDAY, 11))
        self.assertEqual(Appointment.objects.count(), 1)

    def test_cancelled_source_refusal_creates_nothing(self):
        source = self._source(status=Appointment.Status.CANCELLED)
        with self.assertRaises(ValidationError):
            rebook_appointment(source.pk, at(MONDAY, 11))
        self.assertEqual(Appointment.objects.count(), 1)

    def test_unrostered_new_slot_refused(self):
        source = self._source()
        with self.assertRaises(ValidationError):
            rebook_appointment(source, at(MONDAY, 18))
        self.assertEqual(Appointment.objects.count(), 1)
