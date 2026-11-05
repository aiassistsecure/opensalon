import io
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from insights.retention_export import (
    RETENTION_FIELDNAMES, export_retention_csv, export_retention_row,
)
from saloncore.models import Salon
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)

HEADER = ",".join(RETENTION_FIELDNAMES) + "\n"
SEEDED_CSV = HEADER + "2026-11-02,2026-11-08,3,2,6,0.6666666666666666,2.0\n"
SEEDED_ROW = {
    "start_date": "2026-11-02", "end_date": "2026-11-08",
    "active_clients": 3, "repeat_clients": 2, "total_visits": 6,
    "repeat_rate": 0.6666666666666666,
    "average_visits_per_active_client": 2.0,
}
ZERO_CSV = HEADER + "2026-11-02,2026-11-08,0,0,0,0.0,0.0\n"
ZERO_ROW = {
    "start_date": "2026-11-02", "end_date": "2026-11-08",
    "active_clients": 0, "repeat_clients": 0, "total_visits": 0,
    "repeat_rate": 0.0, "average_visits_per_active_client": 0.0,
}


class ExportRetentionFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.clients = [
            Client.objects.create(
                salon=self.salon, first_name=f"C{i}", last_name="Test")
            for i in range(3)
        ]

    def _appt(self, client, day_offset=0, hour=10):
        start = datetime(2026, 11, 2, hour, 0, tzinfo=UTC) + timedelta(
            days=day_offset)
        return Appointment.objects.create(
            client=client, staff_member=self.staff, start=start,
            end=start + timedelta(minutes=45),
            status=Appointment.Status.COMPLETED)

    def _seed(self):
        a, b, c = self.clients
        for offset in (0, 2, 4):
            self._appt(a, day_offset=offset)
        self._appt(b, day_offset=1)
        self._appt(c, day_offset=1)
        self._appt(c, day_offset=3, hour=14)

    def test_row_function_and_csv_byte_identical(self):
        self._seed()
        row = export_retention_row(self.salon, START, END)
        self.assertEqual(row, SEEDED_ROW)
        self.assertEqual(list(row), RETENTION_FIELDNAMES)
        self.assertEqual(export_retention_csv(self.salon, START, END),
                         SEEDED_CSV)

    def test_default_and_explicit_csv_byte_identical(self):
        self._seed()
        for kwargs in ({}, {"format": "csv"}):
            out = io.StringIO()
            call_command("export_retention", salon_id=self.salon.pk,
                         start_date=START, end_date=END, stdout=out, **kwargs)
            self.assertEqual(out.getvalue(), SEEDED_CSV)

    def test_json_is_one_element_list_exact_serialisation(self):
        self._seed()
        row = export_retention_row(self.salon, START, END)
        out = io.StringIO()
        call_command("export_retention", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [SEEDED_ROW])
        self.assertEqual(json.loads(out.getvalue()), [row])
        self.assertEqual(out.getvalue(), json.dumps(
            [row], indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_cli_flag(self):
        self._seed()
        out = io.StringIO()
        call_command("export_retention", "--salon-id", str(self.salon.pk),
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), "--format", "json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [SEEDED_ROW])

    def test_json_output_file(self):
        self._seed()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "retention.json")
            call_command("export_retention", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(json.loads(written), [SEEDED_ROW])
        self.assertEqual(written, json.dumps(
            [SEEDED_ROW], indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertEqual(out.getvalue(), "")

    def test_zero_case_csv_and_json(self):
        self.assertEqual(export_retention_row(self.salon, START, END),
                         ZERO_ROW)
        self.assertEqual(export_retention_csv(self.salon, START, END),
                         ZERO_CSV)
        out = io.StringIO()
        call_command("export_retention", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="json",
                     stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [ZERO_ROW])

    def test_filter_composition_narrower_window(self):
        self._seed()
        start, end = date(2026, 11, 6), date(2026, 11, 8)
        out = io.StringIO()
        call_command("export_retention", salon_id=self.salon.pk,
                     start_date=start, end_date=end, format="json",
                     stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(rows, [export_retention_row(self.salon, start, end)])
        self.assertEqual(rows, [{
            "start_date": "2026-11-06", "end_date": "2026-11-08",
            "active_clients": 1, "repeat_clients": 0, "total_visits": 1,
            "repeat_rate": 0.0, "average_visits_per_active_client": 1.0,
        }])
        out = io.StringIO()
        call_command("export_retention", salon_id=self.salon.pk,
                     start_date=START, end_date=END, format="csv",
                     stdout=out)
        self.assertEqual(out.getvalue(), SEEDED_CSV)

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_retention", salon_id=self.salon.pk,
                         start_date=START, end_date=END, format="xml",
                         stdout=io.StringIO())
