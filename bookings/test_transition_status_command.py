"""Tests for the transition_status management command.

The command is a thin wrapper around
``bookings.lifecycle.transition_status``: these tests pin that
a valid move delegates to the service and persists, and that
invalid transitions, terminal-state moves, unknown statuses,
and unknown appointments surface as ``CommandError`` with the
appointment left unchanged. Fixtures are tiny synthetic
records -- unit logic only.
"""
import datetime
import io

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


class TransitionStatusCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.appointment = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service,
            start=datetime.datetime.combine(
                DAY, datetime.time(9, 0), tzinfo=UTC),
            end=datetime.datetime.combine(
                DAY, datetime.time(9, 45), tzinfo=UTC))

    def _status(self):
        self.appointment.refresh_from_db()
        return self.appointment.status

    def test_valid_transition_delegates_and_persists(self):
        out = io.StringIO()
        call_command(
            "transition_status", appointment_id=self.appointment.pk,
            status="confirmed", stdout=out)
        self.assertEqual(self._status(), Appointment.Status.CONFIRMED)
        self.assertIn("booked -> confirmed", out.getvalue())

    def test_string_args_form(self):
        out = io.StringIO()
        call_command(
            "transition_status", "--appointment-id",
            str(self.appointment.pk), "--status", "cancelled",
            stdout=out)
        self.assertEqual(self._status(), Appointment.Status.CANCELLED)

    def test_full_happy_path_via_command(self):
        for status in ("confirmed", "arrived", "in_service", "completed"):
            call_command(
                "transition_status", appointment_id=self.appointment.pk,
                status=status, stdout=io.StringIO())
        self.assertEqual(self._status(), Appointment.Status.COMPLETED)

    def test_invalid_transition_is_command_error_and_unchanged(self):
        with self.assertRaises(CommandError):
            call_command(
                "transition_status", appointment_id=self.appointment.pk,
                status="completed", stdout=io.StringIO())
        self.assertEqual(self._status(), Appointment.Status.BOOKED)

    def test_same_status_is_command_error_and_unchanged(self):
        with self.assertRaises(CommandError):
            call_command(
                "transition_status", appointment_id=self.appointment.pk,
                status="booked", stdout=io.StringIO())
        self.assertEqual(self._status(), Appointment.Status.BOOKED)

    def test_terminal_status_cannot_transition(self):
        call_command(
            "transition_status", appointment_id=self.appointment.pk,
            status="no_show", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "transition_status", appointment_id=self.appointment.pk,
                status="confirmed", stdout=io.StringIO())
        self.assertEqual(self._status(), Appointment.Status.NO_SHOW)

    def test_unknown_status_is_command_error_and_unchanged(self):
        with self.assertRaises(CommandError):
            call_command(
                "transition_status", appointment_id=self.appointment.pk,
                status="done", stdout=io.StringIO())
        self.assertEqual(self._status(), Appointment.Status.BOOKED)

    def test_unknown_appointment_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "transition_status", appointment_id=999999,
                status="confirmed", stdout=io.StringIO())
