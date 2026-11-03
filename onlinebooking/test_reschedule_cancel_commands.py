"""Tests for reschedule_booking / cancel_booking commands.

Thin wrappers over ``onlinebooking.services``: real runs apply
the service move/cancellation, ``--dry-run`` previews without
writing (read-only validate helpers, NEDB-safe) and
prints the would-be result, and invalid moves (unrostered,
overlap, toggle off, non-cancellable status, unknown or
out-of-salon appointment) surface as ``CommandError`` with
nothing changed. Fixtures are tiny synthetic records.
"""
import datetime
import io

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.services import create_online_booking
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class CommandBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist", online_bookable=True)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))
        self.appt = create_online_booking(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(MONDAY, 10))


class RescheduleBookingCommandTests(CommandBase):
    def test_real_run_moves_and_preserves_duration(self):
        out = io.StringIO()
        call_command("reschedule_booking", appointment_id=self.appt.pk,
                     new_start=at(MONDAY, 13), stdout=out)
        self.appt.refresh_from_db()
        self.assertEqual((self.appt.start, self.appt.end),
                         (at(MONDAY, 13), at(MONDAY, 13, 45)))
        self.assertIn("Rescheduled appointment", out.getvalue())
        self.assertIn(str(self.appt.pk), out.getvalue())

    def test_real_run_string_args_explicit_end_and_salon(self):
        out = io.StringIO()
        call_command("reschedule_booking", "--appointment-id", str(self.appt.pk),
                     "--salon-id", str(self.salon.pk),
                     "--new-start", "2026-11-02T14:00:00+00:00",
                     "--new-end", "2026-11-02T15:00:00+00:00", stdout=out)
        self.appt.refresh_from_db()
        self.assertEqual((self.appt.start, self.appt.end),
                         (at(MONDAY, 14), at(MONDAY, 15)))

    def test_dry_run_prints_move_and_writes_nothing(self):
        out = io.StringIO()
        call_command("reschedule_booking", appointment_id=self.appt.pk,
                     new_start=at(MONDAY, 13), dry_run=True, stdout=out)
        self.appt.refresh_from_db()
        self.assertEqual((self.appt.start, self.appt.end),
                         (at(MONDAY, 10), at(MONDAY, 10, 45)))
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn(at(MONDAY, 13).isoformat(), text)

    def test_dry_run_no_write_regression_count_status_times(self):
        call_command("reschedule_booking", appointment_id=self.appt.pk,
                     new_start=at(MONDAY, 13), dry_run=True,
                     stdout=io.StringIO())
        self.appt.refresh_from_db()
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(self.appt.status, Appointment.Status.BOOKED)
        self.assertEqual((self.appt.start, self.appt.end),
                         (at(MONDAY, 10), at(MONDAY, 10, 45)))

    def test_dry_run_invalid_move_is_command_error_unchanged(self):
        with self.assertRaises(CommandError):
            call_command("reschedule_booking", appointment_id=self.appt.pk,
                         new_start=at(MONDAY, 18), dry_run=True,
                         stdout=io.StringIO())
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.start, at(MONDAY, 10))

    def test_invalid_moves_are_command_errors_unchanged(self):
        create_online_booking(client=self.client, staff_member=self.staff,
                              service=self.service, start=at(MONDAY, 13))
        for target in (at(MONDAY, 18), at(MONDAY, 13)):  # unrostered, overlap
            with self.assertRaises(CommandError):
                call_command("reschedule_booking", appointment_id=self.appt.pk,
                             new_start=target, stdout=io.StringIO())
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.start, at(MONDAY, 10))

    def test_toggle_off_move_is_command_error(self):
        self.staff.online_bookable = False
        self.staff.save(update_fields=["online_bookable"])
        with self.assertRaises(CommandError):
            call_command("reschedule_booking", appointment_id=self.appt.pk,
                         new_start=at(MONDAY, 13), stdout=io.StringIO())
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.start, at(MONDAY, 10))

    def test_unknown_and_out_of_salon_are_command_errors(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        for kwargs in (dict(appointment_id=999999),
                       dict(appointment_id=self.appt.pk, salon_id=999999),
                       dict(appointment_id=self.appt.pk, salon_id=other.pk)):
            with self.assertRaises(CommandError):
                call_command("reschedule_booking", new_start=at(MONDAY, 13),
                             stdout=io.StringIO(), **kwargs)

    def test_unparseable_new_start_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command("reschedule_booking", appointment_id=self.appt.pk,
                         new_start="not-a-time", stdout=io.StringIO())


class CancelBookingCommandTests(CommandBase):
    def test_real_run_cancels_and_keeps_row(self):
        out = io.StringIO()
        call_command("cancel_booking", appointment_id=self.appt.pk, stdout=out)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, Appointment.Status.CANCELLED)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertIn("Cancelled appointment", out.getvalue())

    def test_real_run_string_args_and_salon(self):
        call_command("cancel_booking", "--appointment-id", str(self.appt.pk),
                     "--salon-id", str(self.salon.pk), stdout=io.StringIO())
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, Appointment.Status.CANCELLED)

    def test_dry_run_prints_cancellation_and_writes_nothing(self):
        out = io.StringIO()
        call_command("cancel_booking", appointment_id=self.appt.pk,
                     dry_run=True, stdout=out)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, Appointment.Status.BOOKED)
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn("cancelled", text)

    def test_dry_run_no_write_regression_count_status_times(self):
        call_command("cancel_booking", appointment_id=self.appt.pk,
                     dry_run=True, stdout=io.StringIO())
        self.appt.refresh_from_db()
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(self.appt.status, Appointment.Status.BOOKED)
        self.assertEqual((self.appt.start, self.appt.end),
                         (at(MONDAY, 10), at(MONDAY, 10, 45)))

    def test_dry_run_flag_form(self):
        out = io.StringIO()
        call_command("cancel_booking", "--appointment-id", str(self.appt.pk),
                     "--dry-run", stdout=out)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, Appointment.Status.BOOKED)
        self.assertIn("Dry run", out.getvalue())

    def test_completed_cannot_cancel_real_or_dry_run(self):
        Appointment.objects.filter(pk=self.appt.pk).update(
            status=Appointment.Status.COMPLETED)
        for kw in ({}, {"dry_run": True}):
            with self.assertRaises(CommandError):
                call_command("cancel_booking", appointment_id=self.appt.pk,
                             stdout=io.StringIO(), **kw)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, Appointment.Status.COMPLETED)

    def test_already_cancelled_is_idempotent(self):
        call_command("cancel_booking", appointment_id=self.appt.pk,
                     stdout=io.StringIO())
        out = io.StringIO()
        call_command("cancel_booking", appointment_id=self.appt.pk, stdout=out)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, Appointment.Status.CANCELLED)
        self.assertIn("cancelled", out.getvalue())

    def test_unknown_and_out_of_salon_are_command_errors(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        for kwargs in (dict(appointment_id=999999),
                       dict(appointment_id=self.appt.pk, salon_id=999999),
                       dict(appointment_id=self.appt.pk, salon_id=other.pk)):
            with self.assertRaises(CommandError):
                call_command("cancel_booking", stdout=io.StringIO(), **kwargs)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, Appointment.Status.BOOKED)
