import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase

from bookings.availability import available_slots
from bookings.lifecycle import (
    cancel_appointment,
    create_appointment,
    reschedule_appointment,
    transition_status,
)
from bookings.models import Appointment, AppointmentNote
from clients.models import Client, ClientNote
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class LifecycleBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
        )

    def _create(self, hour=10, **kw):
        kw.setdefault("client", self.client)
        kw.setdefault("staff_member", self.staff)
        kw.setdefault("service", self.service)
        kw.setdefault("start", at(MONDAY, hour))
        return create_appointment(**kw)


class CreateAppointmentTests(LifecycleBase):
    def test_create_defaults_end_from_service_duration_and_booked(self):
        appt = self._create()
        self.assertEqual(appt.end, at(MONDAY, 10, 45))
        self.assertEqual(appt.status, Appointment.Status.BOOKED)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_create_with_explicit_end(self):
        appt = self._create(end=at(MONDAY, 11, 30))
        self.assertEqual(appt.end, at(MONDAY, 11, 30))

    def test_create_outside_roster_rejected(self):
        with self.assertRaises(ValidationError):
            self._create(hour=18)
        with self.assertRaises(ValidationError):
            self._create(hour=8)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_create_on_unrostered_weekday_rejected(self):
        tuesday = MONDAY + datetime.timedelta(days=1)
        with self.assertRaises(ValidationError):
            self._create(start=at(tuesday, 10))
        self.assertEqual(Appointment.objects.count(), 0)

    def test_create_overlapping_existing_rejected_adjacent_ok(self):
        self._create(hour=10)  # 10:00-10:45
        with self.assertRaises(ValidationError):
            self._create(hour=10, start=at(MONDAY, 10, 30))
        adjacent = self._create(start=at(MONDAY, 10, 45))
        self.assertEqual(adjacent.start, at(MONDAY, 10, 45))

    def test_create_naive_and_end_before_start_rejected(self):
        naive = datetime.datetime.combine(MONDAY, datetime.time(10, 0))
        with self.assertRaises(ValidationError):
            self._create(start=naive)
        with self.assertRaises(ValidationError):
            self._create(end=at(MONDAY, 9, 30))

    def test_create_cross_salon_and_inactive_rejected(self):
        other = Salon.objects.create(name="Other")
        outsider = Client.objects.create(
            salon=other, first_name="Out", last_name="Sider"
        )
        with self.assertRaises(ValidationError):
            self._create(client=outsider)
        self.staff.active = False
        self.staff.save()
        with self.assertRaises(ValidationError):
            self._create()

    def test_create_online_requires_online_bookable(self):
        self.staff.online_bookable = False
        self.staff.save()
        with self.assertRaises(ValidationError):
            self._create(online=True)
        appt = self._create(online=False)  # in-salon booking still allowed
        self.assertEqual(appt.staff_member, self.staff)

    def test_create_note_is_appointment_only(self):
        appt = self._create(note="Allergic to X", note_author="Front Desk")
        notes = list(appt.notes.all())
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].body, "Allergic to X")
        self.assertEqual(notes[0].author_name, "Front Desk")
        self.assertEqual(ClientNote.objects.count(), 0)


class TransitionStatusTests(LifecycleBase):
    def test_happy_path_flow(self):
        appt = self._create()
        for status in ("confirmed", "arrived", "in_service", "completed"):
            transition_status(appt, status)
            self.assertEqual(appt.status, status)

    def test_invalid_and_terminal_transitions_rejected(self):
        appt = self._create()
        with self.assertRaises(ValidationError):
            transition_status(appt, Appointment.Status.COMPLETED)
        with self.assertRaises(ValidationError):
            transition_status(appt, Appointment.Status.BOOKED)
        transition_status(appt, Appointment.Status.NO_SHOW)
        with self.assertRaises(ValidationError):
            transition_status(appt, Appointment.Status.CONFIRMED)


class RescheduleAppointmentTests(LifecycleBase):
    def test_reschedule_preserves_duration_and_notes(self):
        appt = self._create(note="Keep me")
        moved = reschedule_appointment(appt, at(MONDAY, 14))
        self.assertEqual(moved.pk, appt.pk)
        self.assertEqual((moved.start, moved.end), (at(MONDAY, 14), at(MONDAY, 14, 45)))
        self.assertEqual([n.body for n in moved.notes.all()], ["Keep me"])
        self.assertEqual(ClientNote.objects.count(), 0)

    def test_reschedule_may_overlap_its_own_old_slot(self):
        appt = self._create(hour=10)
        moved = reschedule_appointment(appt, at(MONDAY, 10, 30))
        self.assertEqual(moved.start, at(MONDAY, 10, 30))

    def test_reschedule_into_another_appointment_rejected(self):
        self._create(hour=10)
        other = self._create(hour=13)
        with self.assertRaises(ValidationError):
            reschedule_appointment(other, at(MONDAY, 10, 15))
        other.refresh_from_db()
        self.assertEqual(other.start, at(MONDAY, 13))

    def test_reschedule_outside_roster_and_terminal_rejected(self):
        appt = self._create()
        with self.assertRaises(ValidationError):
            reschedule_appointment(appt, at(MONDAY, 18))
        cancel_appointment(appt)
        with self.assertRaises(ValidationError):
            reschedule_appointment(appt, at(MONDAY, 12))

    def test_reschedule_to_other_staff_member(self):
        other = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two"
        )
        RosterPattern.objects.create(
            staff_member=other, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
        )
        appt = self._create()
        moved = reschedule_appointment(
            appt, at(MONDAY, 11), new_staff_member=other
        )
        self.assertEqual(moved.staff_member, other)


class CancelAppointmentTests(LifecycleBase):
    def test_cancel_frees_the_slot(self):
        appt = self._create(hour=10)
        cancel_appointment(appt)
        self.assertEqual(appt.status, Appointment.Status.CANCELLED)
        rebooked = self._create(hour=10)
        self.assertNotEqual(rebooked.pk, appt.pk)
        slots = available_slots(self.salon, MONDAY)
        self.assertEqual(len(slots), 1)

    def test_cancel_keeps_row_and_notes(self):
        appt = self._create(note="Why cancelled unknown")
        cancel_appointment(appt)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(AppointmentNote.objects.count(), 1)

    def test_cancel_completed_or_twice_rejected(self):
        appt = self._create()
        for status in ("confirmed", "arrived", "in_service", "completed"):
            transition_status(appt, status)
        with self.assertRaises(ValidationError):
            cancel_appointment(appt)
        other = self._create(hour=13)
        cancel_appointment(other)
        with self.assertRaises(ValidationError):
            cancel_appointment(other)
