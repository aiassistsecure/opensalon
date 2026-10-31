"""Tests for the export_send_totals_detail management command.

The command is a thin wrapper around
``messaging.send_export.export_send_totals_csv``: these tests
pin that its stdout and file output match that service
verbatim, that salon scoping is honoured, and that unknown
salons and unwritable outputs fail cleanly as
``CommandError``.

These tests load the messaging command class explicitly via
``load_command_class("messaging", "export_send_totals_detail")``
and pass that instance to ``call_command`` -- pinning this
app's command, not the global name resolution. That pinning
matters here: the similarly named ``export_send_totals``
command wraps a different service
(``messaging.send_totals_export.export_send_totals_summary_csv``,
a period summary), and these tests also pin that this detail
command neither produces that summary output nor invokes
that summary service.
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

from bookings.models import Appointment
from clients.models import Client
from messaging.models import ReminderSend
from messaging.send_export import export_send_totals_csv
from messaging.send_totals_export import export_send_totals_summary_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)
DAY3 = date(2026, 3, 4)


def _cmd():
    return load_command_class("messaging", "export_send_totals_detail")


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


class ExportSendTotalsDetailCommandTests(TestCase):
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
            _cmd(), salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_csv(self.salon, DAY1, DAY3))

    def test_stdout_matches_service_single_day(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk,
            date_from=DAY1, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_csv(self.salon, DAY1))

    def test_stdout_matches_service_with_cli_args(self):
        out = io.StringIO()
        call_command(
            _cmd(), "--salon-id", str(self.salon.pk),
            "--date-from", DAY1.isoformat(),
            "--date-to", DAY3.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_csv(self.salon, DAY1, DAY3))

    def test_stdout_matches_service_with_alias_kwargs(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk,
            start=DAY1, end=DAY2, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_csv(self.salon, DAY1, DAY2))

    def test_salon_scoping(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_csv(self.salon, DAY1, DAY3))
        # Per-day detail rows: DAY1 email count is this salon's 1.
        self.assertIn(f"{DAY1.isoformat()},email,1", out.getvalue())
        other_out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.other.pk,
            date_from=DAY1, date_to=DAY3, stdout=other_out)
        self.assertEqual(
            other_out.getvalue(),
            export_send_totals_csv(self.other, DAY1, DAY3))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "send_totals_detail.csv")
            call_command(
                _cmd(), salon_id=self.salon.pk,
                date_from=DAY1, date_to=DAY3, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            written,
            export_send_totals_csv(self.salon, DAY1, DAY3))
        self.assertEqual(out.getvalue(), "")

    def test_reversed_range_matches_service_verbatim(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk,
            date_from=DAY3, date_to=DAY1, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_csv(self.salon, DAY3, DAY1))

    def test_output_differs_from_summary_service(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, stdout=out)
        detail_text = out.getvalue()
        summary_text = export_send_totals_summary_csv(
            self.salon, DAY1, DAY3)
        self.assertEqual(
            detail_text, export_send_totals_csv(self.salon, DAY1, DAY3))
        self.assertNotEqual(detail_text, summary_text)
        # Detail header is per-day; summary header is per-period.
        self.assertTrue(
            detail_text.startswith("salon_id,date,channel,count\n"))
        self.assertTrue(summary_text.startswith(
            "salon_id,start_date,end_date,channel,status,count\n"))

    def test_does_not_invoke_summary_service(self):
        target = (
            "messaging.management.commands."
            "export_send_totals_detail.export_send_totals_csv")
        with mock.patch(target, wraps=export_send_totals_csv) as detail, \
                mock.patch(
                    "messaging.send_totals_export."
                    "export_send_totals_summary_csv") as summary:
            out = io.StringIO()
            call_command(
                _cmd(), salon_id=self.salon.pk,
                date_from=DAY1, date_to=DAY3, stdout=out)
        detail.assert_called_once()
        summary.assert_not_called()
        self.assertEqual(
            out.getvalue(),
            export_send_totals_csv(self.salon, DAY1, DAY3))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.pk + 1000,
                date_from=DAY1, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "send_totals_detail.csv")
            with self.assertRaises(CommandError):
                call_command(
                    _cmd(), salon_id=self.salon.pk,
                    date_from=DAY1, output=path, stdout=io.StringIO())
