"""Tests for the export_send_totals management command.

The command is a thin wrapper around
``messaging.send_totals_export.export_send_totals_summary_csv``:
these tests pin that its stdout and file output match that
service verbatim, that salon scoping is honoured, and that
unknown salons and unwritable outputs fail cleanly as
``CommandError``.
"""
import io
import json
import os
import tempfile
from unittest import mock
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.models import ReminderSend
from messaging.send_totals_export import (
    export_send_totals_summary,
    export_send_totals_summary_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY1 = date(2026, 3, 2)
DAY2 = date(2026, 3, 3)
DAY3 = date(2026, 3, 4)


def _at(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=UTC)


class ExportSendTotalsCommandTests(TestCase):
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
            "export_send_totals", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_summary_csv(self.salon, DAY1, DAY3))

    def test_stdout_matches_service_single_day(self):
        out = io.StringIO()
        call_command(
            "export_send_totals", salon_id=self.salon.pk,
            date_from=DAY1, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_summary_csv(self.salon, DAY1))

    def test_stdout_matches_service_with_cli_args(self):
        out = io.StringIO()
        call_command(
            "export_send_totals", "--salon-id", str(self.salon.pk),
            "--date-from", DAY1.isoformat(),
            "--date-to", DAY3.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_summary_csv(self.salon, DAY1, DAY3))

    def test_stdout_matches_service_with_alias_kwargs(self):
        out = io.StringIO()
        call_command(
            "export_send_totals", salon_id=self.salon.pk,
            start=DAY1, end=DAY2, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_summary_csv(self.salon, DAY1, DAY2))

    def test_salon_scoping(self):
        out = io.StringIO()
        call_command(
            "export_send_totals", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_summary_csv(self.salon, DAY1, DAY3))
        self.assertIn("email,sent,1", out.getvalue())
        other_out = io.StringIO()
        call_command(
            "export_send_totals", salon_id=self.other.pk,
            date_from=DAY1, date_to=DAY3, stdout=other_out)
        self.assertEqual(
            other_out.getvalue(),
            export_send_totals_summary_csv(self.other, DAY1, DAY3))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "send_totals.csv")
            call_command(
                "export_send_totals", salon_id=self.salon.pk,
                date_from=DAY1, date_to=DAY3, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            written,
            export_send_totals_summary_csv(self.salon, DAY1, DAY3))
        self.assertEqual(out.getvalue(), "")

    def test_reversed_range_matches_service_verbatim(self):
        out = io.StringIO()
        call_command(
            "export_send_totals", salon_id=self.salon.pk,
            date_from=DAY3, date_to=DAY1, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_summary_csv(self.salon, DAY3, DAY1))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_send_totals", salon_id=self.salon.pk + 1000,
                date_from=DAY1, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "send_totals.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_send_totals", salon_id=self.salon.pk,
                    date_from=DAY1, output=path, stdout=io.StringIO())

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command(
            "export_send_totals", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_summary_csv(self.salon, DAY1, DAY3))

    def test_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_send_totals", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_summary_csv(self.salon, DAY1, DAY3))
        out = io.StringIO()
        call_command(
            "export_send_totals", "--salon-id", str(self.salon.pk),
            "--date-from", DAY1.isoformat(),
            "--date-to", DAY3.isoformat(),
            "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_send_totals_summary_csv(self.salon, DAY1, DAY3))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command(
            "export_send_totals", salon_id=self.salon.pk,
            date_from=DAY1, date_to=DAY3, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_send_totals_summary(self.salon, DAY1, DAY3))
        self.assertEqual(
            out.getvalue(),
            json.dumps(
                export_send_totals_summary(self.salon, DAY1, DAY3),
                indent=2) + "\n")

    def test_json_via_cli_flags(self):
        out = io.StringIO()
        call_command(
            "export_send_totals", "--salon-id", str(self.salon.pk),
            "--date-from", DAY1.isoformat(),
            "--date-to", DAY3.isoformat(),
            "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_send_totals_summary(self.salon, DAY1, DAY3))

    def test_json_composes_with_range_salon_and_aliases(self):
        out = io.StringIO()
        call_command(
            "export_send_totals", salon_id=self.salon.pk,
            start=DAY1, end=DAY2, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_send_totals_summary(self.salon, DAY1, DAY2))
        other_out = io.StringIO()
        call_command(
            "export_send_totals", salon_id=self.other.pk,
            date_from=DAY1, date_to=DAY3, format="json",
            stdout=other_out)
        self.assertEqual(
            json.loads(other_out.getvalue()),
            export_send_totals_summary(self.other, DAY1, DAY3))

    def test_json_output_file_matches_dict_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "send_totals.json")
            call_command(
                "export_send_totals", salon_id=self.salon.pk,
                date_from=DAY1, date_to=DAY3, format="json",
                output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written),
            export_send_totals_summary(self.salon, DAY1, DAY3))
        self.assertEqual(out.getvalue(), "")

    def test_json_reversed_range_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_send_totals", salon_id=self.salon.pk,
            date_from=DAY3, date_to=DAY1, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_send_totals_summary(self.salon, DAY3, DAY1))

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_send_totals", salon_id=self.salon.pk,
                date_from=DAY1, format="xml", stdout=io.StringIO())

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_send_totals", "--salon-id", str(self.salon.pk),
                "--date-from", DAY1.isoformat(),
                "--format", "xml", stdout=io.StringIO())

    def test_json_service_error_raises_command_error(self):
        with mock.patch(
                "messaging.management.commands.export_send_totals."
                "export_send_totals_summary",
                side_effect=ValueError("boom")):
            with self.assertRaises(CommandError):
                call_command(
                    "export_send_totals", salon_id=self.salon.pk,
                    date_from=DAY1, format="json",
                    stdout=io.StringIO())
