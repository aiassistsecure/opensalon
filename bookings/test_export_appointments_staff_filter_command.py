"""Tests for the staff-member filter on the appointments export.

``bookings.export.export_appointments`` and its CSV twin
``export_appointments_csv`` gain one optional ``staff_member``
parameter (default ``None`` = the previous salon-wide output
verbatim), mirroring ``bookings.breaks_export.export_breaks``.
The ``export_appointments`` management command gains one
``--staff-member-id`` flag: the id is resolved to its
``StaffMember`` in the salon and passed through; an unknown id —
or another salon's staff id — raises ``CommandError``. The
filter is read-only. Fixtures are tiny synthetic records --
unit logic only.
"""
import csv
import datetime
import io
import json

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.export import (
    EXPORT_FIELDNAMES,
    export_appointments,
    export_appointments_csv,
)
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


class AppointmentsStaffFilterTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        self.one = self._appt(self.staff, 9)
        self.two = self._appt(self.staff2, 11)
        self.one_cancelled = self._appt(
            self.staff, 13, status=Appointment.Status.CANCELLED)

    def _appt(self, staff, hour, **kw):
        return Appointment.objects.create(
            client=self.client, staff_member=staff,
            start=at(DAY, hour), end=at(DAY, hour + 1), **kw)

    def _ids(self, rows):
        return [row["id"] for row in rows]

    # -- service ------------------------------------------------------
    def test_default_is_salon_wide_and_unchanged(self):
        rows = export_appointments(self.salon, DAY, DAY)
        self.assertEqual(
            self._ids(rows),
            [self.one.pk, self.two.pk, self.one_cancelled.pk])
        self.assertEqual(
            rows, export_appointments(self.salon, DAY, DAY, staff_member=None))
        for row in rows:
            self.assertEqual(list(row.keys()), EXPORT_FIELDNAMES)

    def test_filter_by_instance(self):
        rows = export_appointments(self.salon, DAY, DAY, staff_member=self.staff)
        self.assertEqual(self._ids(rows), [self.one.pk, self.one_cancelled.pk])

    def test_filter_by_pk(self):
        rows = export_appointments(
            self.salon, DAY, DAY, staff_member=self.staff2.pk)
        self.assertEqual(self._ids(rows), [self.two.pk])

    def test_filter_other_salon_staff_exports_empty(self):
        self.assertEqual(
            export_appointments(
                self.salon, DAY, DAY, staff_member=self.other_staff),
            [])

    def test_filter_combines_with_include_cancelled(self):
        rows = export_appointments(
            self.salon, DAY, DAY, include_cancelled=False,
            staff_member=self.staff)
        self.assertEqual(self._ids(rows), [self.one.pk])

    # -- CSV twin -------------------------------------------------------
    def test_csv_default_matches_service_rows(self):
        text = export_appointments_csv(self.salon, DAY, DAY)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [int(row["id"]) for row in parsed],
            self._ids(export_appointments(self.salon, DAY, DAY)))
        self.assertEqual(text.splitlines()[0], ",".join(EXPORT_FIELDNAMES))

    def test_csv_filtered_by_staff(self):
        text = export_appointments_csv(
            self.salon, DAY, DAY, staff_member=self.staff2)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual([int(row["id"]) for row in parsed], [self.two.pk])
        self.assertEqual(
            [row["staff_member_id"] for row in parsed],
            [str(self.staff2.pk)])

    def test_csv_no_match_is_header_only(self):
        self.assertEqual(
            export_appointments_csv(
                self.salon, DAY, DAY, staff_member=self.other_staff),
            ",".join(EXPORT_FIELDNAMES) + "\n")

    # -- command --------------------------------------------------------
    def test_command_unfiltered_matches_service(self):
        out = io.StringIO()
        call_command("export_appointments", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            json.dumps(export_appointments(self.salon, DAY, DAY), indent=2)
            + "\n")

    def test_command_filtered_cli_json_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_appointments", "--salon-id", str(self.salon.pk),
            "--date-from", DAY.isoformat(), "--date-to", DAY.isoformat(),
            "--staff-member-id", str(self.staff.pk), stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_appointments(self.salon, DAY, DAY, staff_member=self.staff))

    def test_command_filtered_kwargs_pk_matches_service(self):
        out = io.StringIO()
        call_command("export_appointments", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY,
                     staff_member_id=self.staff2.pk, stdout=out)
        self.assertEqual(self._ids(json.loads(out.getvalue())), [self.two.pk])

    def test_command_filtered_kwargs_instance_matches_service(self):
        out = io.StringIO()
        call_command("export_appointments", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY,
                     staff_member_id=self.staff, stdout=out)
        self.assertEqual(
            self._ids(json.loads(out.getvalue())),
            [self.one.pk, self.one_cancelled.pk])

    def test_command_filtered_csv_matches_csv_twin(self):
        out = io.StringIO()
        call_command("export_appointments", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, format="csv",
                     staff_member_id=self.staff.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_appointments_csv(
                self.salon, DAY, DAY, staff_member=self.staff))

    def test_command_unknown_staff_id_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_appointments", "--salon-id", str(self.salon.pk),
                "--date-from", DAY.isoformat(),
                "--staff-member-id", str(self.staff.pk + 1000),
                stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_appointments", salon_id=self.salon.pk,
                         date_from=DAY, staff_member_id=999999,
                         stdout=io.StringIO())

    def test_command_other_salon_staff_id_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_appointments", salon_id=self.salon.pk,
                         date_from=DAY, date_to=DAY,
                         staff_member_id=self.other_staff.pk,
                         stdout=io.StringIO())
