import csv
import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from insights.retention import repeat_visit_retention
from insights.retention_export import (
    RETENTION_FIELDNAMES,
    export_retention_csv,
    retention_csv,
)
from saloncore.models import Salon
from team.models import StaffMember

UTC = ZoneInfo("UTC")
START = date(2026, 11, 2)
END = date(2026, 11, 8)


class RetentionExportCsvTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist"
        )
        self.clients = [
            Client.objects.create(
                salon=self.salon, first_name=f"C{i}", last_name="Test"
            )
            for i in range(3)
        ]
        self.other_client = Client.objects.create(
            salon=self.other, first_name="Other", last_name="Client"
        )

    def _appt(self, client, *, day_offset=0, hour=10, staff=None,
              status=Appointment.Status.COMPLETED):
        start = datetime(2026, 11, 2, hour, 0, tzinfo=UTC) + timedelta(
            days=day_offset
        )
        return Appointment.objects.create(
            client=client, staff_member=staff or self.staff,
            start=start, end=start + timedelta(minutes=45),
            status=status,
        )

    def _rows(self, salon=None, start=START, end=END, **kwargs):
        text = export_retention_csv(salon or self.salon, start, end, **kwargs)
        return list(csv.DictReader(io.StringIO(text)))

    def test_header(self):
        text = export_retention_csv(self.salon, START, END)
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, RETENTION_FIELDNAMES)
        self.assertEqual(RETENTION_FIELDNAMES, [
            "start_date", "end_date", "active_clients", "repeat_clients",
            "total_visits", "repeat_rate",
            "average_visits_per_active_client",
        ])

    def test_row_matches_service_output(self):
        a, b, c = self.clients
        for offset in (0, 2, 4):
            self._appt(a, day_offset=offset)
        self._appt(b, day_offset=1)
        self._appt(c, day_offset=1)
        self._appt(c, day_offset=3, hour=14)
        self._appt(self.other_client, staff=self.other_staff)
        result = repeat_visit_retention(self.salon, START, END)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["start_date"], result.start_date.isoformat())
        self.assertEqual(row["end_date"], result.end_date.isoformat())
        self.assertEqual(int(row["active_clients"]), result.active_clients)
        self.assertEqual(int(row["repeat_clients"]), result.repeat_clients)
        self.assertEqual(int(row["total_visits"]), result.total_visits)
        self.assertAlmostEqual(float(row["repeat_rate"]), result.repeat_rate)
        self.assertAlmostEqual(
            float(row["average_visits_per_active_client"]),
            result.average_visits_per_active_client,
        )
        # Concrete fixture expectations (3 active, 2 repeat, 6 visits).
        self.assertEqual(
            (result.active_clients, result.repeat_clients,
             result.total_visits), (3, 2, 6),
        )

    def test_alias_and_keyword_bounds_passthrough(self):
        self._appt(self.clients[0])
        text = retention_csv(
            self.salon, start_date=START, end_date=END
        )
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]["total_visits"]), 1)

    def test_empty_range_is_single_zero_row_matching_service(self):
        result = repeat_visit_retention(self.salon, START, END)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["start_date"], result.start_date.isoformat())
        self.assertEqual(row["end_date"], result.end_date.isoformat())
        self.assertEqual(int(row["active_clients"]), 0)
        self.assertEqual(int(row["repeat_clients"]), 0)
        self.assertEqual(int(row["total_visits"]), 0)
        self.assertEqual(float(row["repeat_rate"]), 0.0)
        self.assertEqual(
            float(row["average_visits_per_active_client"]), 0.0
        )

    def test_read_only(self):
        self._appt(self.clients[0])
        self._appt(self.clients[0], day_offset=1)
        before = Appointment.objects.count()
        export_retention_csv(self.salon, START, END)
        self.assertEqual(Appointment.objects.count(), before)
