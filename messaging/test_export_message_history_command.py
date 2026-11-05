import datetime
import io
import json
import os
import tempfile
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.history_export import (
    export_history_summary,
    export_history_summary_csv,
)
from messaging.models import ReminderSend
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = ZoneInfo("UTC")
DAY = datetime.date(2026, 3, 2)
NEXT = DAY + datetime.timedelta(days=1)


class ExportMessageHistoryCommandTests(TestCase):
    def setUp(self):
        salon = Salon.objects.create(name="Example Salon")
        staff = StaffMember.objects.create(
            salon=salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(
            salon=salon, name="Haircuts")
        service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        client = Client.objects.create(
            salon=salon, first_name="Client1", last_name="Example",
            email="c1@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        start = timezone.now() + timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)
        ReminderSend.objects.create(
            appointment=appt, client=client, channel="email",
            status=ReminderSend.Status.SENT,
            sent_at=datetime.datetime.combine(
                DAY, time(9), tzinfo=UTC))

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_message_history",
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_history_summary_csv(DAY, DAY))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_message_history",
            "--start-date", DAY.isoformat(),
            "--end-date", NEXT.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(), export_history_summary_csv(DAY, NEXT))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "message_history.csv")
            call_command(
                "export_message_history",
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_history_summary_csv(DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def _add_other_salon_send(self):
        other = Salon.objects.create(name="Other Salon")
        staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        category = ServiceCategory.objects.create(
            salon=other, name="Other Haircuts")
        service = Service.objects.create(
            category=category, name="Other Haircut", service_minutes=45)
        client = Client.objects.create(
            salon=other, first_name="Other", last_name="Example",
            email="other@example.com", phone="555-0200",
            sms_opt_in=True, email_opt_in=True)
        start = timezone.now() + timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=service,
            start=start, end=start + timedelta(minutes=45),
            status=Appointment.Status.BOOKED)
        ReminderSend.objects.create(
            appointment=appt, client=client, channel="sms",
            status=ReminderSend.Status.SENT,
            sent_at=datetime.datetime.combine(
                DAY, time(10), tzinfo=UTC))
        return other

    def test_salon_id_scopes_export_and_omitted_is_all_salons(self):
        other = self._add_other_salon_send()
        salon = Salon.objects.get(name="Example Salon")
        out = io.StringIO()
        call_command(
            "export_message_history",
            start_date=DAY, end_date=DAY, salon_id=salon.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_history_summary_csv(DAY, DAY, salon=salon))
        self.assertNotEqual(
            out.getvalue(), export_history_summary_csv(DAY, DAY))
        scoped_other = io.StringIO()
        call_command(
            "export_message_history",
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--salon-id", str(other.pk), stdout=scoped_other)
        self.assertEqual(
            scoped_other.getvalue(),
            export_history_summary_csv(DAY, DAY, salon=other))
        unscoped = io.StringIO()
        call_command(
            "export_message_history",
            start_date=DAY, end_date=DAY, stdout=unscoped)
        self.assertEqual(
            unscoped.getvalue(), export_history_summary_csv(DAY, DAY))

    def test_unknown_salon_id_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_message_history",
                start_date=DAY, end_date=DAY, salon_id=999999,
                stdout=io.StringIO())

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_message_history",
                start_date="not-a-date", end_date=DAY,
                stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_message_history",
                "--start-date", "2026-13-40",
                "--end-date", DAY.isoformat(), stdout=io.StringIO())

    def test_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_message_history",
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())

    def test_default_is_csv_byte_identical(self):
        default_out = io.StringIO()
        call_command(
            "export_message_history",
            start_date=DAY, end_date=DAY, stdout=default_out)
        csv_out = io.StringIO()
        call_command(
            "export_message_history",
            start_date=DAY, end_date=DAY, format="csv", stdout=csv_out)
        self.assertEqual(default_out.getvalue(), csv_out.getvalue())
        self.assertEqual(
            default_out.getvalue(), export_history_summary_csv(DAY, DAY))

    def test_explicit_csv_via_cli_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_message_history",
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(), export_history_summary_csv(DAY, DAY))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command(
            "export_message_history",
            start_date=DAY, end_date=DAY, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()), export_history_summary(DAY, DAY))
        self.assertEqual(
            out.getvalue(),
            json.dumps(
                export_history_summary(DAY, DAY),
                indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_via_cli_with_salon_filter_matches_dict_service(self):
        other = self._add_other_salon_send()
        salon = Salon.objects.get(name="Example Salon")
        out = io.StringIO()
        call_command(
            "export_message_history",
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--salon-id", str(salon.pk), "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_history_summary(DAY, DAY, salon=salon))
        self.assertNotEqual(
            json.loads(out.getvalue()), export_history_summary(DAY, DAY))
        other_out = io.StringIO()
        call_command(
            "export_message_history",
            start_date=DAY, end_date=DAY, salon_id=other.pk,
            format="json", stdout=other_out)
        self.assertEqual(
            json.loads(other_out.getvalue()),
            export_history_summary(DAY, DAY, salon=other))

    def test_json_output_file_parses_and_equals_dict_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "message_history.json")
            call_command(
                "export_message_history",
                start_date=DAY, end_date=NEXT, format="json",
                output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written), export_history_summary(DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_message_history",
                start_date=DAY, end_date=DAY, format="xml",
                stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_message_history",
                "--start-date", DAY.isoformat(),
                "--end-date", DAY.isoformat(),
                "--format", "xml", stdout=io.StringIO())

    def test_json_reversed_range_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_message_history",
                start_date=NEXT, end_date=DAY, format="json",
                stdout=io.StringIO())
