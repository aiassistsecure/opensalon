"""Tests for --format on the export_noshow_rate command.

CSV (default) must be byte-identical to the service; JSON must
parse and equal ``[row]`` where row is
:func:`bookings.noshow_rate_export.export_noshow_rate_row`
(Group D shape (ii): a one-element list), serialised via
``DjangoJSONEncoder``, and must agree with the CSV row.
Fixtures are tiny synthetic records.
"""
import csv
import datetime
import io
import json
from unittest import mock

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.models import Appointment
from bookings.noshow_rate_export import (
    NOSHOW_RATE_EXPORT_FIELDNAMES,
    export_noshow_rate_csv,
    export_noshow_rate_row,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 10, 26)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class ExportNoShowRateFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        S = Appointment.Status
        self._appt(at(DAY, 9), S.COMPLETED)
        self._appt(at(DAY, 10), S.COMPLETED)
        self._appt(at(DAY, 11), S.NO_SHOW)
        self._appt(at(DAY, 12), S.BOOKED)
        self._appt(at(DAY, 13), S.CANCELLED, updated=at(DAY, 14))
        self._appt(at(DAY, 15), S.CANCELLED, updated=at(DAY, 13))

    def _appt(self, start, status, *, updated=None):
        a = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, start=start,
            end=start + datetime.timedelta(minutes=45), status=status)
        if updated is not None:
            Appointment.objects.filter(pk=a.pk).update(updated_at=updated)
        return a

    def _row(self, salon=None):
        return export_noshow_rate_row(salon or self.salon, DAY, DAY)

    def test_row_function_and_csv_byte_identical(self):
        row = self._row()
        self.assertEqual(list(row), NOSHOW_RATE_EXPORT_FIELDNAMES)
        self.assertEqual(row, {
            "salon_id": self.salon.pk,
            "start_date": "2026-10-26", "end_date": "2026-10-26",
            "total_appointments": 6, "completed": 2, "no_shows": 1,
            "cancelled": 2, "late_cancellations": 1,
            "no_show_rate_percent": "16.67",
            "late_cancel_rate_percent": "16.67"})
        self.assertEqual(
            export_noshow_rate_csv(self.salon, DAY, DAY),
            ",".join(NOSHOW_RATE_EXPORT_FIELDNAMES) + "\n"
            + f"{self.salon.pk},2026-10-26,2026-10-26,6,2,1,2,1,16.67,16.67\n")

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_noshow_rate", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_noshow_rate_csv(self.salon, DAY, DAY))

    def test_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command("export_noshow_rate", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, format="csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_noshow_rate_csv(self.salon, DAY, DAY))
        out = io.StringIO()
        call_command("export_noshow_rate", "--salon-id", str(self.salon.pk),
                     "--date-from", DAY.isoformat(),
                     "--date-to", DAY.isoformat(),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_noshow_rate_csv(self.salon, DAY, DAY))

    def test_json_parses_and_equals_one_element_list_row(self):
        out = io.StringIO()
        call_command("export_noshow_rate", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, format="json", stdout=out)
        row = self._row()
        parsed = json.loads(out.getvalue())
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed, [row])
        self.assertEqual(out.getvalue(), json.dumps(
            [row], indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_csv_json_agreement(self):
        csv_out, json_out = io.StringIO(), io.StringIO()
        call_command("export_noshow_rate", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, stdout=csv_out)
        call_command("export_noshow_rate", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, format="json",
                     stdout=json_out)
        csv_rows = list(csv.DictReader(io.StringIO(csv_out.getvalue())))
        json_rows = json.loads(json_out.getvalue())
        self.assertEqual(len(csv_rows), 1)
        self.assertEqual(len(json_rows), 1)
        crow, jrow = csv_rows[0], json_rows[0]
        self.assertEqual(list(jrow.keys()), list(crow.keys()))
        for key, val in jrow.items():
            self.assertEqual(crow[key], "" if val is None else str(val))

    def test_empty_salon(self):
        empty = Salon.objects.create(name="Empty Salon", timezone="UTC")
        row = self._row(empty)
        self.assertEqual(row["total_appointments"], 0)
        self.assertEqual(row["no_show_rate_percent"], "")
        self.assertEqual(row["late_cancel_rate_percent"], "")
        out = io.StringIO()
        call_command("export_noshow_rate", salon_id=empty.pk,
                     date_from=DAY, date_to=DAY, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [row])
        out = io.StringIO()
        call_command("export_noshow_rate", salon_id=empty.pk,
                     date_from=DAY, date_to=DAY, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_noshow_rate_csv(empty, DAY, DAY))

    def test_output_file_json_and_csv(self):
        row = self._row()
        for fmt, expected in (
                ("json", json.dumps([row], indent=2,
                                     cls=DjangoJSONEncoder) + "\n"),
                ("csv", export_noshow_rate_csv(self.salon, DAY, DAY))):
            m = mock.mock_open()
            with mock.patch(
                    "bookings.management.commands.export_noshow_rate.open", m):
                call_command("export_noshow_rate", salon_id=self.salon.pk,
                             date_from=DAY, date_to=DAY, format=fmt,
                             output="noshow_rate.out", stdout=io.StringIO())
            written = "".join(c.args[0] for c in m().write.call_args_list)
            self.assertEqual(written, expected)

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_noshow_rate", salon_id=self.salon.pk,
                         date_from=DAY, date_to=DAY, format="xml",
                         stdout=io.StringIO())
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_noshow_rate", "--salon-id",
                         str(self.salon.pk), "--date-from", DAY.isoformat(),
                         "--date-to", DAY.isoformat(), "--format", "xml",
                         stdout=io.StringIO())
