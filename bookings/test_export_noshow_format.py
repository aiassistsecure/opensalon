"""Tests for the export_noshow command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_noshow_csv``
service), that JSON parses to the dict rows from the new twin
``export_noshow`` -- the same rows the CSV is built from --
serialised with ``DjangoJSONEncoder`` (indent=2 + trailing
newline), and that unknown formats fail cleanly.

Note: this command is loaded explicitly via
``load_command_class("bookings", "export_noshow")``
for the same global-namespace reason as the sibling format
tests.
"""
import csv
import datetime
import io
import json
import os
import tempfile

from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.models import Appointment
from bookings.noshow_export import (
    NOSHOW_EXPORT_FIELDNAMES,
    export_noshow,
    export_noshow_csv,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 10, 26)  # a Monday, in the past
EMPTY_DAY = DAY - datetime.timedelta(days=7)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


def _cmd():
    return load_command_class("bookings", "export_noshow")


def _expected_json(salon, date_from, date_to=None):
    return json.dumps(export_noshow(salon, date_from, date_to),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportNoshowFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.appt_early = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service,
            start=at(DAY, 9), end=at(DAY, 9, 45),
            status=Appointment.Status.NO_SHOW)
        self.appt_late = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=None, service_name="Imported Cut",
            start=at(DAY, 14), end=at(DAY, 14, 45),
            status=Appointment.Status.NO_SHOW)
        Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service,
            start=at(DAY, 11), end=at(DAY, 11, 45),
            status=Appointment.Status.COMPLETED)
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Other Stylist")
        other_client = Client.objects.create(
            salon=self.other_salon, first_name="Other", last_name="Guest")
        Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=self.service,
            start=at(DAY, 10), end=at(DAY, 10, 45),
            status=Appointment.Status.NO_SHOW)

    def _pinned_rows(self):
        return [
            {"id": self.appt_late.pk, "client_id": self.client.pk,
             "client_name": "Test Example",
             "staff_member_id": self.staff.pk, "staff_name": "Stylist One",
             "service_id": "", "service_name": "Imported Cut",
             "start": at(DAY, 14).isoformat(),
             "end": at(DAY, 14, 45).isoformat(), "status": "no_show"},
            {"id": self.appt_early.pk, "client_id": self.client.pk,
             "client_name": "Test Example",
             "staff_member_id": self.staff.pk, "staff_name": "Stylist One",
             "service_id": self.service.pk, "service_name": "Haircut",
             "start": at(DAY, 9).isoformat(),
             "end": at(DAY, 9, 45).isoformat(), "status": "no_show"},
        ]

    def _pinned_csv(self):
        return (
            ",".join(NOSHOW_EXPORT_FIELDNAMES) + "\n"
            f"{self.appt_late.pk},{self.client.pk},Test Example,"
            f"{self.staff.pk},Stylist One,,Imported Cut,"
            f"{at(DAY, 14).isoformat()},{at(DAY, 14, 45).isoformat()},"
            "no_show\n"
            f"{self.appt_early.pk},{self.client.pk},Test Example,"
            f"{self.staff.pk},Stylist One,{self.service.pk},Haircut,"
            f"{at(DAY, 9).isoformat()},{at(DAY, 9, 45).isoformat()},"
            "no_show\n"
        )

    def _call(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("date_from", DAY)
        call_command(_cmd(), salon_id=self.salon.pk, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_noshow_csv(self.salon, DAY, None), self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(
            self._call(), export_noshow_csv(self.salon, DAY, None))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(self._call(format="csv"), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--date-from", DAY.isoformat(), "--format", "csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_noshow(self.salon, DAY, None)
        self.assertEqual(rows, self._pinned_rows())
        parsed = list(csv.DictReader(io.StringIO(
            export_noshow_csv(self.salon, DAY, None))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows],
            parsed)
        self.assertEqual([list(row) for row in rows],
                         [NOSHOW_EXPORT_FIELDNAMES] * len(rows))

    def test_json_parses_and_equals_dict_twin(self):
        text = self._call(format="json")
        rows = export_noshow(self.salon, DAY, None)
        self.assertEqual(json.loads(text), _parsed(rows))
        self.assertEqual(json.loads(text), self._pinned_rows())
        self.assertEqual(text, _expected_json(self.salon, DAY))
        self.assertIn("Stylist One", text)

    def test_json_rows_equal_csv_rows(self):
        json_rows = json.loads(self._call(format="json"))
        csv_rows = list(csv.DictReader(io.StringIO(
            export_noshow_csv(self.salon, DAY, None))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--date-from", DAY.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon, DAY))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "noshow.json")
            call_command(_cmd(), salon_id=self.salon.pk, date_from=DAY,
                         format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "noshow.csv")
            call_command(_cmd(), salon_id=self.salon.pk, date_from=DAY,
                         output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_day_json_and_csv(self):
        self.assertEqual(
            json.loads(self._call(format="json", date_from=EMPTY_DAY)), [])
        self.assertEqual(export_noshow(self.salon, EMPTY_DAY, None), [])
        self.assertEqual(
            self._call(date_from=EMPTY_DAY),
            ",".join(NOSHOW_EXPORT_FIELDNAMES) + "\n")

    def test_json_scopes_to_salon(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.other_salon.pk, date_from=DAY,
                     format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["staff_name"], "Other Stylist")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(_cmd(), "--salon-id", str(self.salon.pk),
                         "--date-from", DAY.isoformat(), "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=999999, date_from=DAY,
                         format="json", stdout=io.StringIO())

    def test_no_date_from_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=self.salon.pk,
                         format="json", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command(_cmd(), salon_id=self.salon.pk, date_from=DAY,
                             format="json", output=path,
                             stdout=io.StringIO())
