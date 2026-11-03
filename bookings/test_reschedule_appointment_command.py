"""Tests for the reschedule_appointment management command.

Thin wrapper over ``bookings.lifecycle.reschedule_appointment``:
real runs apply the service move, ``--dry-run`` previews via
the read-only validate twin without writing (NEDB-safe), the
staff member's online-booking toggle is NOT enforced (the
phone / walk-in path -- the key difference from
onlinebooking's ``reschedule_booking``), and invalid moves
surface as ``CommandError`` with nothing changed. Fixtures
are tiny synthetic records -- unit logic only.
"""
import datetime
import io

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.lifecycle import create_appointment
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class RescheduleAppointmentCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One", online_bookable=True)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))
        self.appt = create_appointment(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(MONDAY, 10))

    def _move(self, out=None, **kw):
        kw.setdefault("appointment_id", self.appt.pk)
        kw.setdefault("new_start", at(MONDAY, 13))
        return call_command("reschedule_appointment",
                            stdout=out or io.StringIO(), **kw)

    def test_real_run_moves_and_preserves_duration(self):
        out = io.StringIO()
        self._move(out=out)
        self.appt.refresh_from_db()
        self.assertEqual((self.appt.start, self.appt.end),
                         (at(MONDAY, 13), at(MONDAY, 13, 45)))
        self.assertIn("Rescheduled appointment", out.getvalue())
        self.assertIn(str(self.appt.pk), out.getvalue())

    def test_real_run_string_args_explicit_end_and_salon(self):
        out = io.StringIO()
        call_command("reschedule_appointment", "--appointment-id",
                     str(self.appt.pk), "--salon-id", str(self.salon.pk),
                     "--new-start", "2026-11-02T14:00:00+00:00",
                     "--new-end", "2026-11-02T15:00:00+00:00", stdout=out)
        self.appt.refresh_from_db()
        self.assertEqual((self.appt.start, self.appt.end),
                         (at(MONDAY, 14), at(MONDAY, 15)))

    def test_toggle_off_move_still_applies(self):
        # The phone/walk-in path must NOT be gated by the
        # online-booking toggle (onlinebooking's command is).
        self.staff.online_bookable = False
        self.staff.save(update_fields=["online_bookable"])
        self._move()
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.start, at(MONDAY, 13))

    def test_toggle_off_dry_run_still_validates(self):
        self.staff.online_bookable = False
        self.staff.save(update_fields=["online_bookable"])
        out = io.StringIO()
        self._move(out=out, dry_run=True)
        self.assertIn("Dry run", out.getvalue())
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.start, at(MONDAY, 10))

    def test_dry_run_prints_move_and_writes_nothing(self):
        out = io.StringIO()
        self._move(out=out, dry_run=True)
        self.appt.refresh_from_db()
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(self.appt.status, Appointment.Status.BOOKED)
        self.assertEqual((self.appt.start, self.appt.end),
                         (at(MONDAY, 10), at(MONDAY, 10, 45)))
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn(at(MONDAY, 13).isoformat(), text)
        self.assertIn("no appointment moved", text)

    def test_dry_run_flag_form(self):
        out = io.StringIO()
        call_command("reschedule_appointment", "--appointment-id",
                     str(self.appt.pk), "--new-start",
                     "2026-11-02T13:00:00+00:00", "--dry-run", stdout=out)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.start, at(MONDAY, 10))
        self.assertIn("Dry run", out.getvalue())

    def test_dry_run_invalid_move_is_command_error_unchanged(self):
        with self.assertRaises(CommandError):
            self._move(new_start=at(MONDAY, 18), dry_run=True)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.start, at(MONDAY, 10))

    def test_invalid_moves_are_command_errors_unchanged(self):
        create_appointment(client=self.client, staff_member=self.staff,
                           service=self.service, start=at(MONDAY, 14))
        for target in (at(MONDAY, 18), at(MONDAY, 14)):  # unrostered, overlap
            with self.assertRaises(CommandError):
                self._move(new_start=target)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.start, at(MONDAY, 10))

    def test_non_reschedulable_status_is_command_error(self):
        Appointment.objects.filter(pk=self.appt.pk).update(
            status=Appointment.Status.COMPLETED)
        for kw in ({}, {"dry_run": True}):
            with self.assertRaises(CommandError):
                self._move(**kw)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.start, at(MONDAY, 10))

    def test_unknown_and_out_of_salon_are_command_errors(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        for kwargs in (dict(appointment_id=999999),
                       dict(appointment_id=self.appt.pk, salon_id=999999),
                       dict(appointment_id=self.appt.pk, salon_id=other.pk)):
            with self.assertRaises(CommandError):
                call_command("reschedule_appointment",
                             new_start=at(MONDAY, 13),
                             stdout=io.StringIO(), **kwargs)

    def test_unparseable_and_naive_new_start_are_command_errors(self):
        naive = datetime.datetime.combine(MONDAY, datetime.time(13, 0))
        for value in ("not-a-time", naive):
            with self.assertRaises(CommandError):
                self._move(new_start=value)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.start, at(MONDAY, 10))
