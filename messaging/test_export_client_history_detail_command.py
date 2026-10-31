"""Tests for the export_client_history_detail management command.

The command is a thin wrapper around
``messaging.history_export.export_client_history_csv``: these
tests pin that its stdout and file output match that service
verbatim, that ``--limit`` passes through, and that unknown
salons/clients and unwritable outputs fail cleanly as
``CommandError``.

These tests load the messaging command class explicitly via
``load_command_class("messaging", "export_client_history_detail")``
and pass that instance to ``call_command`` -- pinning this app's
command, not global name resolution. That pinning matters: the
global ``export_client_history`` command is owned by the bookings
app and wraps a different service, and these tests also pin that
this detail command neither produces that appointment output nor
invokes that bookings service.
"""
import io
import os
import tempfile
from datetime import date, datetime, time, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase
from django.utils import timezone

from bookings.client_history_export import (
    export_client_history_csv as bookings_export_csv,
)
from bookings.models import Appointment
from clients.models import Client
from messaging.history_export import export_client_history_csv
from messaging.models import ReminderSend
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)


def _cmd():
    return load_command_class("messaging", "export_client_history_detail")


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


class ExportClientHistoryDetailCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Client1", last_name="Example",
            email="c1@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        self.other_client = Client.objects.create(
            salon=self.salon, first_name="Client2", last_name="Example",
            email="c2@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        self._send(self.client, "email", _at(DAY1, 9))
        self._send(self.client, "sms", _at(DAY2, 9))
        self._send(self.other_client, "email", _at(DAY1, 10))

    def _send(self, client, channel, when):
        start = timezone.now() + timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)
        return ReminderSend.objects.create(
            appointment=appt, client=client, channel=channel,
            status="sent", sent_at=when)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk, client_id=self.client.pk,
            stdout=out)
        self.assertEqual(
            out.getvalue(), export_client_history_csv(self.client))

    def test_stdout_matches_service_with_cli_args(self):
        out = io.StringIO()
        call_command(
            _cmd(), "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk), stdout=out)
        self.assertEqual(
            out.getvalue(), export_client_history_csv(self.client))

    def test_stdout_matches_service_with_client_alias(self):
        out = io.StringIO()
        call_command(
            _cmd(), "--salon-id", str(self.salon.pk),
            "--client", str(self.client.pk), stdout=out)
        self.assertEqual(
            out.getvalue(), export_client_history_csv(self.client))

    def test_client_scoping(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk, client_id=self.client.pk,
            stdout=out)
        self.assertEqual(
            out.getvalue(), export_client_history_csv(self.client))
        self.assertEqual(len(out.getvalue().splitlines()), 3)
        other_out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk,
            client_id=self.other_client.pk, stdout=other_out)
        self.assertEqual(
            other_out.getvalue(),
            export_client_history_csv(self.other_client))
        self.assertEqual(len(other_out.getvalue().splitlines()), 2)

    def test_limit_passes_through(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk, client_id=self.client.pk,
            limit=1, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(self.client, limit=1))
        self.assertEqual(len(out.getvalue().splitlines()), 2)

    def test_empty_client_is_header_only(self):
        empty = Client.objects.create(
            salon=self.salon, first_name="Client3", last_name="Example",
            email="c3@example.com", phone="555-0100")
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk, client_id=empty.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_client_history_csv(empty))
        self.assertEqual(len(out.getvalue().splitlines()), 1)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "client_history_detail.csv")
            call_command(
                _cmd(), salon_id=self.salon.pk, client_id=self.client.pk,
                output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(written, export_client_history_csv(self.client))
        self.assertEqual(out.getvalue(), "")

    def test_output_differs_from_bookings_service(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk, client_id=self.client.pk,
            stdout=out)
        detail_text = out.getvalue()
        bookings_text = bookings_export_csv(self.salon, self.client)
        self.assertEqual(
            detail_text, export_client_history_csv(self.client))
        self.assertNotEqual(detail_text, bookings_text)
        self.assertTrue(detail_text.startswith(
            "id,appointment_id,client_id,channel,status,sent_at,detail\n"))

    def test_does_not_invoke_bookings_service(self):
        target = (
            "messaging.management.commands."
            "export_client_history_detail.export_client_history_csv")
        with mock.patch(target, wraps=export_client_history_csv) as detail, \
                mock.patch(
                    "bookings.client_history_export."
                    "export_client_history_csv") as bookings:
            out = io.StringIO()
            call_command(
                _cmd(), salon_id=self.salon.pk, client_id=self.client.pk,
                stdout=out)
        detail.assert_called_once()
        bookings.assert_not_called()
        self.assertEqual(
            out.getvalue(), export_client_history_csv(self.client))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.pk + 1000,
                client_id=self.client.pk, stdout=io.StringIO())

    def test_unknown_client_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.pk,
                client_id=self.client.pk + 1000, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "detail.csv")
            with self.assertRaises(CommandError):
                call_command(
                    _cmd(), salon_id=self.salon.pk,
                    client_id=self.client.pk, output=path,
                    stdout=io.StringIO())
