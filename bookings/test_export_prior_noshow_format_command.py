"""Tests for --format on the export_prior_noshow management command.

CSV (default) must be byte-identical to the service; JSON must
parse and equal prior_noshow_rows for the same arguments, and
CSV/JSON rows must agree. Fixtures are tiny synthetic records.
"""
import csv
import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.models import Appointment
from bookings.prior_noshow_export import export_prior_noshow_csv, prior_noshow_rows
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
PRIOR_DAY = DAY - datetime.timedelta(days=1)
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


def _decoded(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportPriorNoshowFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        self.client2 = Client.objects.create(
            salon=self.salon, first_name="Second", last_name="Client")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        NS, CP = Appointment.Status.NO_SHOW, Appointment.Status.COMPLETED

        def appt(day, hour, status, staff=None, client=None):
            return Appointment.objects.create(
                client=client or self.client,
                staff_member=staff or self.staff, service=self.service,
                start=at(day, hour),
                end=at(day, hour) + datetime.timedelta(minutes=45),
                status=status)

        appt(PRIOR_DAY, 9, NS)
        appt(PRIOR_DAY, 10, CP)
        appt(PRIOR_DAY, 11, NS, staff=self.staff2, client=self.client2)
        appt(DAY, 9, NS)
        appt(DAY, 10, NS)
        appt(DAY, 11, CP)

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_prior_noshow", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, now=NOW, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_noshow_csv(self.salon, DAY, DAY, now=NOW))

    def test_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_noshow", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, now=NOW, format="csv",
                     stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_noshow_csv(self.salon, DAY, DAY, now=NOW))
        out = io.StringIO()
        call_command("export_prior_noshow", "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
                     "--now", NOW.isoformat(), "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_noshow_csv(self.salon, DAY, DAY, now=NOW))

    def test_json_parses_and_equals_rows(self):
        out = io.StringIO()
        call_command("export_prior_noshow", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, now=NOW, format="json",
                     stdout=out)
        rows = prior_noshow_rows(self.salon, DAY, DAY, now=NOW)
        self.assertEqual(json.loads(out.getvalue()), _decoded(rows))
        self.assertEqual(out.getvalue(),
                         json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_csv_json_row_agreement(self):
        csv_out, json_out = io.StringIO(), io.StringIO()
        call_command("export_prior_noshow", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, now=NOW, stdout=csv_out)
        call_command("export_prior_noshow", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, now=NOW, format="json",
                     stdout=json_out)
        csv_rows = list(csv.DictReader(io.StringIO(csv_out.getvalue())))
        json_rows = json.loads(json_out.getvalue())
        rows = prior_noshow_rows(self.salon, DAY, DAY, now=NOW)
        self.assertEqual(len(csv_rows), len(json_rows))
        self.assertEqual(len(csv_rows), len(rows))
        for crow, jrow, row in zip(csv_rows, json_rows, rows):
            self.assertEqual(list(jrow.keys()), list(crow.keys()))
            for key, val in row.items():
                if key.endswith("percent_change"):
                    expected_csv = "" if val is None else f"{val:.2f}"
                elif key in ("current_rate", "prior_rate", "rate_delta"):
                    expected_csv = f"{val:.4f}"
                else:
                    expected_csv = str(val)
                self.assertEqual(crow[key], expected_csv, key)
                self.assertEqual(jrow[key], _decoded([row])[0][key], key)

    def test_json_empty(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        out = io.StringIO()
        call_command("export_prior_noshow", salon_id=other.pk,
                     start_date=DAY, end_date=DAY, now=NOW, format="json",
                     stdout=out)
        rows = prior_noshow_rows(other, DAY, DAY, now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["section"], "total")
        self.assertEqual(json.loads(out.getvalue()), _decoded(rows))
        self.assertEqual(out.getvalue(),
                         json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_filters_compose(self):
        out = io.StringIO()
        call_command("export_prior_noshow", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, now=NOW, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         _decoded(prior_noshow_rows(self.salon, DAY, DAY, now=NOW)))
        early = datetime.datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
        out = io.StringIO()
        call_command("export_prior_noshow", "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
                     "--now", early.isoformat(), "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         _decoded(prior_noshow_rows(self.salon, DAY, DAY, now=early)))

    def test_json_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior.json")
            call_command("export_prior_noshow", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, now=NOW, format="json",
                         output=path, stdout=io.StringIO())
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        rows = prior_noshow_rows(self.salon, DAY, DAY, now=NOW)
        self.assertEqual(written,
                         json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_noshow", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, now=NOW, format="xml",
                         stdout=io.StringIO())
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_noshow", "--salon-id", str(self.salon.pk),
                         "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
                         "--format", "xml", stdout=io.StringIO())
