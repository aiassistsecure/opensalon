import csv
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.utilization import staff_utilization
from bookings.utilization_export import UTILIZATION_FIELDNAMES, export_utilization_csv
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MON = datetime.date(2026, 11, 2)
TUE = datetime.date(2026, 11, 3)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class UtilizationExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9), end_time=datetime.time(17))
        Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=self.service,
            start=at(MON, 9), end=at(MON, 13))

    def test_header_and_rows_match_service(self):
        rows = list(csv.DictReader(io.StringIO(
            export_utilization_csv(self.salon, MON, TUE))))
        header = list(csv.reader(io.StringIO(export_utilization_csv(self.salon, MON))))[0]
        self.assertEqual(header, UTILIZATION_FIELDNAMES)
        report = staff_utilization(self.salon, MON, TUE)
        self.assertEqual(len(rows), len(report.by_staff))
        row, svc = rows[0], report.by_staff[0]
        self.assertEqual(row, {
            "staff_member_id": str(svc.staff_member_id),
            "staff_name": "Stylist One",
            "start_date": "2026-11-02", "end_date": "2026-11-03",
            "appointment_count": "1", "booked_minutes": "240",
            "rostered_minutes": "480", "utilization": "0.5",
        })

    def test_zero_rostered_exports_zero_utilization(self):
        rows = list(csv.DictReader(io.StringIO(
            export_utilization_csv(self.salon, TUE))))
        self.assertEqual(rows[0]["rostered_minutes"], "0")
        self.assertEqual(rows[0]["utilization"], "0.0")

    def test_reversed_range_header_only_and_read_only(self):
        text = export_utilization_csv(self.salon, TUE, MON)
        self.assertEqual(list(csv.reader(io.StringIO(text))),
                         [UTILIZATION_FIELDNAMES])
        self.assertEqual(Appointment.objects.count(), 1)


class ExportUtilizationCommandTests(TestCase):
    def setUp(self):
        UtilizationExportTests.setUp(self)

    def test_stdout_and_file_match_service(self):
        out = io.StringIO()
        call_command("export_utilization", salon_id=self.salon.pk,
                     date_from=MON, date_to=TUE, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_utilization_csv(self.salon, MON, TUE))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "util.csv")
            call_command("export_utilization", "--salon-id", str(self.salon.pk),
                         "--date-from", MON.isoformat(), "--date-to", TUE.isoformat(),
                         "--output", path, stdout=io.StringIO())
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(fh.read(),
                                 export_utilization_csv(self.salon, MON, TUE))

    def test_unknown_salon_missing_and_bad_date_fail(self):
        with self.assertRaises(CommandError):
            call_command("export_utilization", salon_id=self.salon.pk + 1000,
                         date_from=MON, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_utilization", salon_id=self.salon.pk,
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_utilization", "--salon-id", str(self.salon.pk),
                         "--date-from", "not-a-date", stdout=io.StringIO())
