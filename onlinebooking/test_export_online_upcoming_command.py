"""Tests for the export_online_upcoming management command.

The command is a thin wrapper around
``onlinebooking.export_upcoming.export_upcoming_csv``: these
tests pin that its stdout and file output match that service
verbatim, that its now/days/start/horizon arguments forward
to the service, and that an unknown salon, invalid arguments,
and unwritable output fail cleanly as ``CommandError``.
Fixtures are tiny synthetic records -- unit logic only.

Note: the global name ``export_upcoming`` is owned by the
``bookings`` app, so these tests load this app's command
class explicitly via
``load_command_class("onlinebooking", "export_online_upcoming")``
and pass that instance to ``call_command`` -- pinning this
app's command, not the global name resolution.
"""
import csv
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.export_upcoming import export_upcoming_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def _cmd():
    return load_command_class("onlinebooking", "export_online_upcoming")


def at(days, hour=10):
    return NOW + datetime.timedelta(days=days, hours=hour - 12)


class ExportOnlineUpcomingCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)
        self.soon = self._appt(at(1))
        self.far = self._appt(at(30))
        self._appt(at(1, 11), origin="phone")
        self._appt(at(2), status="cancelled")
        self._appt(NOW - datetime.timedelta(hours=1))

    def _appt(self, start, **kw):
        return Appointment.objects.create(
            client=kw.pop("client", self.client),
            staff_member=kw.pop("staff_member", self.staff),
            service=kw.pop("service", self.service),
            start=start, end=start + datetime.timedelta(hours=1),
            status=kw.pop("status", "booked"),
            origin=kw.pop("origin", "online"), **kw)

    def exported_ids(self, text):
        return [int(r["id"]) for r in csv.DictReader(io.StringIO(text))]

    def run_export(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("now", NOW)
        call_command(_cmd(), stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service(self):
        out = self.run_export()
        self.assertEqual(out, export_upcoming_csv(self.salon, now=NOW))
        self.assertEqual(self.exported_ids(out), [self.soon.pk, self.far.pk])

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(
            _cmd(), "--salon-id", str(self.salon.pk),
            "--now", NOW.isoformat(), "--days", "7", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_upcoming_csv(self.salon, now=NOW, days=7))
        self.assertEqual(self.exported_ids(out.getvalue()), [self.soon.pk])

    def test_days_and_horizon_days_forward_to_service(self):
        out = self.run_export(days=7)
        self.assertEqual(
            out, export_upcoming_csv(self.salon, now=NOW, days=7))
        out = self.run_export(horizon_days=7)
        self.assertEqual(
            out, export_upcoming_csv(
                self.salon, now=NOW, horizon_days=7))
        self.assertEqual(self.exported_ids(out), [self.soon.pk])
        self.assertEqual(self.run_export(days=0),
                         export_upcoming_csv(self.salon, now=NOW, days=0))

    def test_start_alias_forwards_to_service(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, start=NOW, stdout=out)
        self.assertEqual(
            out.getvalue(), export_upcoming_csv(self.salon, start=NOW))
        self.assertEqual(
            self.exported_ids(out.getvalue()), [self.soon.pk, self.far.pk])

    def test_salon_scoping_excludes_other_salon(self):
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Mallory")
        other_client = Client.objects.create(
            salon=self.other_salon, first_name="Out", last_name="Sider")
        foreign = self._appt(
            at(1, 11), client=other_client, staff_member=other_staff)
        out = self.run_export()
        self.assertNotIn(foreign.pk, self.exported_ids(out))
        other_out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.other_salon.pk, now=NOW, stdout=other_out)
        self.assertEqual(self.exported_ids(other_out.getvalue()), [foreign.pk])

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "online_upcoming.csv")
            out = self.run_export(output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(), export_upcoming_csv(self.salon, now=NOW))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(salon_id=self.salon.pk + 999)

    def test_invalid_now_and_start_raise_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(now="not-a-datetime")
        with self.assertRaises(CommandError):
            self.run_export(start="not-a-datetime")

    def test_invalid_days_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(days="seven")

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "online_upcoming.csv")
            with self.assertRaises(CommandError):
                self.run_export(output=path)
