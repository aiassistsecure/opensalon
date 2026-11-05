"""Tests for the export_send management command.

The command is a thin wrapper around
``messaging.send_export.export_sends_csv``: these tests pin
that its stdout and file output match that service verbatim,
that salon scoping is honoured, and that unknown salons and
unwritable outputs fail cleanly as ``CommandError``.
"""
import io
import os
import tempfile
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.models import ReminderSend
from messaging.send_export import export_sends_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)
DAY3 = date(2026, 3, 4)


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


class ExportSendCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self._n = 0
        self._send(self.salon, self.staff, "email", _at(DAY1, 9))
        self._send(self.salon, self.staff, "sms", _at(DAY2, 9))
        self._send(self.other, self.other_staff, "email", _at(DAY1, 9))

    def _send(self, salon, staff, channel, when):
        self._n += 1
        client = Client.objects.create(
            salon=salon, first_name=f"C{self._n}", last_name="Example",
            email=f"c{self._n}@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        start = timezone.now() + timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=self.service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)
        return ReminderSend.objects.create(
            appointment=appt, client=client, channel=channel,
            status="sent", sent_at=when)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY1, DAY3))

    def test_stdout_matches_service_single_day(self):
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            date_from=DAY1, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY1))

    def test_stdout_matches_service_with_cli_args(self):
        out = io.StringIO()
        call_command(
            "export_send", "--salon-id", str(self.salon.pk),
            "--date-from", DAY1.isoformat(),
            "--date-to", DAY3.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY1, DAY3))

    def test_stdout_matches_service_with_alias_kwargs(self):
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            start=DAY1, end=DAY2, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY1, DAY2))

    def test_salon_scoping(self):
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY1, DAY3))
        # Own salon has 2 sends in range; other salon's send excluded.
        self.assertEqual(out.getvalue().count("\n"), 3)
        other_out = io.StringIO()
        call_command(
            "export_send", salon_id=self.other.pk,
            date_from=DAY1, date_to=DAY3, stdout=other_out)
        self.assertEqual(
            other_out.getvalue(),
            export_sends_csv(self.other, DAY1, DAY3))
        self.assertEqual(other_out.getvalue().count("\n"), 2)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sends.csv")
            call_command(
                "export_send", salon_id=self.salon.pk,
                date_from=DAY1, date_to=DAY3, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            written,
            export_sends_csv(self.salon, DAY1, DAY3))
        self.assertEqual(out.getvalue(), "")

    def test_reversed_range_matches_service_verbatim(self):
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            date_from=DAY3, date_to=DAY1, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY3, DAY1))

    def test_appointment_id_filters_to_one_appointment(self):
        target = ReminderSend.objects.filter(
            client__salon=self.salon).order_by("id").first()
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3,
            appointment_id=target.appointment_id, stdout=out)
        appointment = Appointment.objects.get(pk=target.appointment_id)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(
                self.salon, DAY1, DAY3, appointment=appointment))
        self.assertEqual(out.getvalue().count("\n"), 2)

    def test_appointment_id_with_cli_args(self):
        target = ReminderSend.objects.filter(
            client__salon=self.salon).order_by("id").first()
        out = io.StringIO()
        call_command(
            "export_send", "--salon-id", str(self.salon.pk),
            "--date-from", DAY1.isoformat(),
            "--date-to", DAY3.isoformat(),
            "--appointment-id", str(target.appointment_id), stdout=out)
        appointment = Appointment.objects.get(pk=target.appointment_id)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(
                self.salon, DAY1, DAY3, appointment=appointment))

    def test_no_appointment_id_is_salon_wide_default(self):
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY1, DAY3, appointment=None))

    def test_unknown_appointment_id_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_send", salon_id=self.salon.pk,
                date_from=DAY1, appointment_id=999999,
                stdout=io.StringIO())

    def test_appointment_from_other_salon_raises_command_error(self):
        foreign = Appointment.objects.filter(
            client__salon=self.other).order_by("id").first()
        with self.assertRaises(CommandError):
            call_command(
                "export_send", salon_id=self.salon.pk,
                date_from=DAY1, appointment_id=foreign.pk,
                stdout=io.StringIO())

    def test_channel_filters_to_one_channel(self):
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, channel="sms", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY1, DAY3, channel="sms"))
        # Own salon has 1 sms send in range (header + 1 row).
        self.assertEqual(out.getvalue().count("\n"), 2)

    def test_channel_with_cli_args(self):
        out = io.StringIO()
        call_command(
            "export_send", "--salon-id", str(self.salon.pk),
            "--date-from", DAY1.isoformat(),
            "--date-to", DAY3.isoformat(),
            "--channel", "email", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY1, DAY3, channel="email"))

    def test_no_channel_is_all_channels_default(self):
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY1, DAY3, channel=None))

    def test_channel_composes_with_appointment_id(self):
        target = ReminderSend.objects.filter(
            client__salon=self.salon, channel="email").order_by(
                "id").first()
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3,
            appointment_id=target.appointment_id, channel="sms",
            stdout=out)
        appointment = Appointment.objects.get(pk=target.appointment_id)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(
                self.salon, DAY1, DAY3, appointment=appointment,
                channel="sms"))
        # That appointment's only send is on email: header only.
        self.assertEqual(out.getvalue().count("\n"), 1)

    def test_status_filters_to_matching_status(self):
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, status="sent", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY1, DAY3, status="sent"))
        # Both own-salon sends are stored as sent (header + 2 rows).
        self.assertEqual(out.getvalue().count("\n"), 3)

    def test_status_with_cli_args(self):
        out = io.StringIO()
        call_command(
            "export_send", "--salon-id", str(self.salon.pk),
            "--date-from", DAY1.isoformat(),
            "--date-to", DAY3.isoformat(),
            "--status", "sent", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY1, DAY3, status="sent"))

    def test_no_status_is_all_statuses_default(self):
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(self.salon, DAY1, DAY3, status=None))

    def test_status_composes_with_appointment_id_and_channel(self):
        target = ReminderSend.objects.filter(
            client__salon=self.salon, channel="email").order_by(
                "id").first()
        out = io.StringIO()
        call_command(
            "export_send", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3,
            appointment_id=target.appointment_id, channel="email",
            status="sent", stdout=out)
        appointment = Appointment.objects.get(pk=target.appointment_id)
        self.assertEqual(
            out.getvalue(),
            export_sends_csv(
                self.salon, DAY1, DAY3, appointment=appointment,
                channel="email", status="sent"))
        self.assertEqual(out.getvalue().count("\n"), 2)

    def test_unknown_status_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_send", salon_id=self.salon.pk,
                date_from=DAY1, date_to=DAY3, status="pigeon",
                stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_send", "--salon-id", str(self.salon.pk),
                "--date-from", DAY1.isoformat(),
                "--status", "failed", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_send", salon_id=self.salon.pk + 1000,
                date_from=DAY1, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "sends.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_send", salon_id=self.salon.pk,
                    date_from=DAY1, output=path, stdout=io.StringIO())
