"""Tests for the export_history management command.

The command is a thin wrapper around
``onlinebooking.export_history.export_history_csv``: these
tests pin that its stdout and file output match that service
verbatim, that salon/client scoping and the now/limit
arguments forward to the service, and that an unknown salon,
an unknown client, an invalid now, and unwritable output fail
cleanly as ``CommandError``. Fixtures are tiny synthetic
records -- unit logic only.
"""
import csv
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.export_history import export_history_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(day_offset, hour=10):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12)


class ExportHistoryCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        self.other_client = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)
        self.newer = self._appt(at(-1), client=self.client)
        self.older = self._appt(at(-2), client=self.other_client)

    def _appt(self, start, client=None, staff=None, service=None, **kw):
        return Appointment.objects.create(
            client=client or self.client,
            staff_member=staff or self.staff,
            service=service or self.service,
            start=start, end=start + datetime.timedelta(hours=1),
            status=kw.pop("status", "booked"), origin="online", **kw)

    def exported_ids(self, text):
        return [int(r["id"]) for r in csv.DictReader(io.StringIO(text))]

    def run_export(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("now", NOW)
        call_command("export_history", stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service_salon_wide(self):
        out = self.run_export()
        self.assertEqual(out, export_history_csv(self.salon, None, now=NOW))
        self.assertEqual(
            self.exported_ids(out), [self.newer.pk, self.older.pk])

    def test_stdout_matches_service_for_client(self):
        out = self.run_export(client_id=self.client.pk)
        self.assertEqual(
            out, export_history_csv(self.salon, self.client, now=NOW))
        self.assertEqual(self.exported_ids(out), [self.newer.pk])

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(
            "export_history", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk),
            "--now", NOW.isoformat(), "--limit", "1", stdout=out)
        self.assertEqual(
            out.getvalue(), export_history_csv(
                self.salon, self.client, now=NOW, limit=1))

    def test_limit_forwards_to_service(self):
        out = self.run_export(limit=1)
        self.assertEqual(
            out, export_history_csv(self.salon, None, now=NOW, limit=1))
        self.assertEqual(self.exported_ids(out), [self.newer.pk])

    def test_salon_scoping_excludes_other_salon(self):
        outsider = Client.objects.create(
            salon=self.other_salon, first_name="Out", last_name="Sider")
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Mallory")
        foreign = self._appt(at(-1, 11), client=outsider, staff=other_staff)
        out = self.run_export()
        self.assertEqual(out, export_history_csv(self.salon, None, now=NOW))
        self.assertNotIn(foreign.pk, self.exported_ids(out))
        out_other = self.run_export(client_id=outsider.pk)
        self.assertEqual(
            out_other, export_history_csv(self.salon, outsider, now=NOW))
        self.assertEqual(self.exported_ids(out_other), [])

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "history.csv")
            out = self.run_export(client_id=self.client.pk, output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(), export_history_csv(
                        self.salon, self.client, now=NOW))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(salon_id=self.salon.pk + 999)

    def test_unknown_client_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(client_id=self.client.pk + 999)

    def test_invalid_now_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(now="not-a-datetime")

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "history.csv")
            with self.assertRaises(CommandError):
                self.run_export(output=path)

    def test_window_string_args_match_service(self):
        out = io.StringIO()
        call_command(
            "export_history", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk), "--now", NOW.isoformat(),
            "--start-date", "2026-11-01", "--end-date", "2026-11-01",
            stdout=out)
        self.assertEqual(
            out.getvalue(), export_history_csv(
                self.salon, self.client, now=NOW,
                start_date=datetime.date(2026, 11, 1),
                end_date=datetime.date(2026, 11, 1)))
        self.assertEqual(self.exported_ids(out.getvalue()), [self.newer.pk])

    def test_window_kwargs_match_service(self):
        out = self.run_export(
            client_id=self.client.pk,
            start_date=datetime.date(2026, 10, 31))
        self.assertEqual(
            out, export_history_csv(
                self.salon, self.client, now=NOW,
                start_date=datetime.date(2026, 10, 31)))
        self.assertEqual(self.exported_ids(out), [self.newer.pk])

    def test_window_alias_flags_match_service(self):
        out = io.StringIO()
        call_command(
            "export_history", "--salon-id", str(self.salon.pk),
            "--now", NOW.isoformat(),
            "--date-from", "2026-10-31", "--date-to", "2026-10-31",
            stdout=out)
        self.assertEqual(
            out.getvalue(), export_history_csv(
                self.salon, None, now=NOW,
                start_date=datetime.date(2026, 10, 31),
                end_date=datetime.date(2026, 10, 31)))
        self.assertEqual(self.exported_ids(out.getvalue()), [self.older.pk])

    def test_window_composes_with_limit(self):
        out = self.run_export(
            limit=1, start_date=datetime.date(2026, 10, 31),
            end_date=datetime.date(2026, 10, 31))
        self.assertEqual(self.exported_ids(out), [self.older.pk])

    def test_status_string_arg_matches_service(self):
        cancelled = self._appt(at(-1, 11), status="cancelled")
        out = io.StringIO()
        call_command(
            "export_history", "--salon-id", str(self.salon.pk),
            "--now", NOW.isoformat(), "--status", "cancelled", stdout=out)
        self.assertEqual(
            out.getvalue(), export_history_csv(
                self.salon, None, now=NOW, status="cancelled"))
        self.assertEqual(self.exported_ids(out.getvalue()), [cancelled.pk])

    def test_status_kwarg_matches_service(self):
        cancelled = self._appt(
            at(-1, 11), client=self.client, status="cancelled")
        out = self.run_export(client_id=self.client.pk, status="cancelled")
        self.assertEqual(
            out, export_history_csv(
                self.salon, self.client, now=NOW, status="cancelled"))
        self.assertEqual(self.exported_ids(out), [cancelled.pk])

    def test_status_composes_with_window_and_limit(self):
        self._appt(at(-1, 11), status="cancelled")
        completed = self._appt(at(-2, 11), status="completed")
        out = self.run_export(
            status="completed", limit=1,
            start_date=datetime.date(2026, 10, 31),
            end_date=datetime.date(2026, 10, 31))
        self.assertEqual(self.exported_ids(out), [completed.pk])

    def test_no_status_is_previous_output(self):
        out = self.run_export()
        self.assertEqual(
            out, export_history_csv(self.salon, None, now=NOW, status=None))

    def test_bad_start_date_raises(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(
                "export_history", "--salon-id", str(self.salon.pk),
                "--start-date", "not-a-date", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            self.run_export(start_date="not-a-date")
