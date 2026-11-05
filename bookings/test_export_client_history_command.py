"""Tests for the export_client_history management command.

The command is a thin wrapper around
``bookings.client_history_export.export_client_history_csv``:
these tests pin that its stdout and file output match that
service verbatim and that unknown salons/clients and bad
arguments fail cleanly. Fixtures are tiny synthetic records --
unit logic only.
"""
import datetime
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.client_history_export import (
    CLIENT_HISTORY_EXPORT_FIELDNAMES,
    export_client_history_csv,
)
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(day_offset, hour):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12)


class ExportClientHistoryCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=self.level)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"))
        self.past = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(-1, 9),
            end=at(-1, 9) + datetime.timedelta(minutes=45),
            status=Appointment.Status.COMPLETED)
        self.future = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(3, 9),
            end=at(3, 9) + datetime.timedelta(minutes=45))

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_client_history", salon_id=self.salon.pk,
            client_id=self.client.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(self.salon, self.client))

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(
            "export_client_history", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(self.salon, self.client))

    def test_upcoming_only_and_now_match_service(self):
        out = io.StringIO()
        call_command(
            "export_client_history", salon_id=self.salon.pk,
            client_id=self.client.pk, upcoming_only=True, now=NOW,
            stdout=out)
        expected = export_client_history_csv(
            self.salon, self.client, upcoming_only=True, now=NOW)
        self.assertEqual(out.getvalue(), expected)
        self.assertIn(self.future.start.isoformat(), out.getvalue())
        self.assertNotIn(self.past.start.isoformat(), out.getvalue())

    def test_upcoming_only_with_string_now_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_client_history", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk), "--upcoming-only",
            "--now", NOW.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(
                self.salon, self.client, upcoming_only=True, now=NOW))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "history.csv")
            call_command(
                "export_client_history", salon_id=self.salon.pk,
                client_id=self.client.pk, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_client_history_csv(self.salon, self.client))
        self.assertEqual(out.getvalue(), "")

    def test_cross_salon_client_is_header_only_verbatim(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        out = io.StringIO()
        call_command(
            "export_client_history", salon_id=other.pk,
            client_id=self.client.pk, stdout=out)
        self.assertEqual(
            out.getvalue(), export_client_history_csv(other, self.client))
        self.assertEqual(
            out.getvalue(),
            ",".join(CLIENT_HISTORY_EXPORT_FIELDNAMES) + "\n")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_client_history", salon_id=self.salon.pk + 1000,
                client_id=self.client.pk, stdout=io.StringIO())

    def test_unknown_client_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_client_history", salon_id=self.salon.pk,
                client_id=self.client.pk + 1000, stdout=io.StringIO())

    def test_bad_now_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_client_history", salon_id=self.salon.pk,
                client_id=self.client.pk, now="not-a-datetime",
                stdout=io.StringIO())

    def test_bad_now_string_arg_raises(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(
                "export_client_history", "--salon-id", str(self.salon.pk),
                "--client-id", str(self.client.pk),
                "--now", "not-a-datetime", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "history.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_client_history", salon_id=self.salon.pk,
                    client_id=self.client.pk, output=path,
                    stdout=io.StringIO())


class ExportClientHistoryWindowCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=self.level)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        self.past = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(-1, 9),
            end=at(-1, 9) + datetime.timedelta(minutes=45),
            status=Appointment.Status.COMPLETED)
        self.future = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(3, 9),
            end=at(3, 9) + datetime.timedelta(minutes=45))

    def test_window_string_args_match_service(self):
        out = io.StringIO()
        call_command(
            "export_client_history", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk),
            "--start-date", "2026-11-01", "--end-date", "2026-11-01",
            stdout=out)
        expected = export_client_history_csv(
            self.salon, self.client,
            start_date=datetime.date(2026, 11, 1),
            end_date=datetime.date(2026, 11, 1))
        self.assertEqual(out.getvalue(), expected)
        self.assertIn(self.past.start.isoformat(), out.getvalue())
        self.assertNotIn(self.future.start.isoformat(), out.getvalue())

    def test_window_kwargs_match_service(self):
        out = io.StringIO()
        call_command(
            "export_client_history", salon_id=self.salon.pk,
            client_id=self.client.pk,
            start_date=datetime.date(2026, 11, 3), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(
                self.salon, self.client,
                start_date=datetime.date(2026, 11, 3)))

    def test_window_alias_flags_match_service(self):
        out = io.StringIO()
        call_command(
            "export_client_history", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk),
            "--date-from", "2026-11-05", "--date-to", "2026-11-05",
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(
                self.salon, self.client,
                start_date=datetime.date(2026, 11, 5),
                end_date=datetime.date(2026, 11, 5)))
        self.assertIn(self.future.start.isoformat(), out.getvalue())

    def test_window_composes_with_upcoming_only(self):
        out = io.StringIO()
        call_command(
            "export_client_history", salon_id=self.salon.pk,
            client_id=self.client.pk, upcoming_only=True, now=NOW,
            end_date=datetime.date(2026, 11, 4), stdout=out)
        self.assertEqual(
            out.getvalue(),
            ",".join(CLIENT_HISTORY_EXPORT_FIELDNAMES) + "\n")

    def test_bad_start_date_raises(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(
                "export_client_history", "--salon-id", str(self.salon.pk),
                "--client-id", str(self.client.pk),
                "--start-date", "not-a-date", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_client_history", salon_id=self.salon.pk,
                client_id=self.client.pk, start_date="not-a-date",
                stdout=io.StringIO())


class ExportClientHistoryStatusCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=self.level)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        self.past = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(-1, 9),
            end=at(-1, 9) + datetime.timedelta(minutes=45),
            status=Appointment.Status.COMPLETED)
        self.future = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(3, 9),
            end=at(3, 9) + datetime.timedelta(minutes=45))

    def test_status_flag_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_client_history", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk),
            "--status", "completed", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(self.salon, self.client, status="completed"))
        self.assertIn(self.past.start.isoformat(), out.getvalue())
        self.assertNotIn(self.future.start.isoformat(), out.getvalue())

    def test_status_kwarg_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_client_history", salon_id=self.salon.pk,
            client_id=self.client.pk, status="booked", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(self.salon, self.client, status="booked"))

    def test_status_composes_with_upcoming_and_window(self):
        out = io.StringIO()
        call_command(
            "export_client_history", salon_id=self.salon.pk,
            client_id=self.client.pk, upcoming_only=True, now=NOW,
            status="completed", stdout=out)
        self.assertEqual(
            out.getvalue(),
            ",".join(CLIENT_HISTORY_EXPORT_FIELDNAMES) + "\n")
        out = io.StringIO()
        call_command(
            "export_client_history", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk),
            "--start-date", "2026-11-01", "--end-date", "2026-11-01",
            "--status", "completed", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(
                self.salon, self.client,
                start_date=datetime.date(2026, 11, 1),
                end_date=datetime.date(2026, 11, 1), status="completed"))
        self.assertIn(self.past.start.isoformat(), out.getvalue())

    def test_unknown_status_is_header_only(self):
        out = io.StringIO()
        call_command(
            "export_client_history", salon_id=self.salon.pk,
            client_id=self.client.pk, status="nope", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(self.salon, self.client, status="nope"))
        self.assertEqual(
            out.getvalue(),
            ",".join(CLIENT_HISTORY_EXPORT_FIELDNAMES) + "\n")

    def test_no_status_is_default(self):
        out = io.StringIO()
        call_command(
            "export_client_history", salon_id=self.salon.pk,
            client_id=self.client.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(self.salon, self.client, status=None))


class ExportClientHistoryServiceCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=self.level)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        self.service2 = Service.objects.create(
            category=cat, name="Colour", service_minutes=60)
        self.past = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=at(-1, 9),
            end=at(-1, 9) + datetime.timedelta(minutes=45),
            status=Appointment.Status.COMPLETED)
        self.future = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service2, start=at(3, 9),
            end=at(3, 9) + datetime.timedelta(minutes=45))

    def test_service_flag_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_client_history", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk),
            "--service-id", str(self.service.pk), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(
                self.salon, self.client, service=self.service))
        self.assertIn(self.past.start.isoformat(), out.getvalue())
        self.assertNotIn(self.future.start.isoformat(), out.getvalue())

    def test_service_kwargs_match_service(self):
        for kwargs in ({"service_id": self.service2.pk},
                       {"service_id": self.service2},
                       {"service": self.service2}):
            out = io.StringIO()
            call_command(
                "export_client_history", salon_id=self.salon.pk,
                client_id=self.client.pk, stdout=out, **kwargs)
            self.assertEqual(
                out.getvalue(),
                export_client_history_csv(
                    self.salon, self.client, service=self.service2))

    def test_service_composes_with_status_window_upcoming(self):
        out = io.StringIO()
        call_command(
            "export_client_history", salon_id=self.salon.pk,
            client_id=self.client.pk, service_id=self.service.pk,
            status="completed", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(
                self.salon, self.client, service=self.service,
                status="completed"))
        self.assertIn(self.past.start.isoformat(), out.getvalue())
        out = io.StringIO()
        call_command(
            "export_client_history", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk),
            "--start-date", "2026-11-05", "--end-date", "2026-11-05",
            "--service-id", str(self.service2.pk), stdout=out)
        self.assertIn(self.future.start.isoformat(), out.getvalue())
        out = io.StringIO()
        call_command(
            "export_client_history", salon_id=self.salon.pk,
            client_id=self.client.pk, upcoming_only=True, now=NOW,
            service_id=self.service.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            ",".join(CLIENT_HISTORY_EXPORT_FIELDNAMES) + "\n")

    def test_unknown_service_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_client_history", "--salon-id", str(self.salon.pk),
                "--client-id", str(self.client.pk),
                "--service-id", str(self.service.pk + 1000),
                stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_client_history", salon_id=self.salon.pk,
                client_id=self.client.pk, service_id=999999,
                stdout=io.StringIO())

    def test_no_service_is_default(self):
        out = io.StringIO()
        call_command(
            "export_client_history", salon_id=self.salon.pk,
            client_id=self.client.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_client_history_csv(self.salon, self.client, service=None))
