import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.bookable_slots_export import (
    EXPORT_FIELDNAMES,
    export_bookable_slots,
    export_bookable_slots_csv,
)
from onlinebooking.services import bookable_slots
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class BookableSlotsExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.online = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist", online_bookable=True
        )
        self.offline = StaffMember.objects.create(
            salon=self.salon, display_name="Offline Stylist", online_bookable=False
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        for staff in (self.online, self.offline):
            RosterPattern.objects.create(
                staff_member=staff, weekday=0,
                start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
            )

    def test_rows_match_service_intervals_and_csv_agrees(self):
        records = export_bookable_slots(self.salon, self.service, MONDAY)
        expected = bookable_slots(self.salon, self.service, MONDAY)
        self.assertEqual(len(records), sum(len(r.intervals) for r in expected))
        self.assertEqual(list(records[0].keys()), EXPORT_FIELDNAMES)
        row = records[0]
        self.assertEqual(row["salon_id"], self.salon.pk)
        self.assertEqual(row["service_id"], self.service.pk)
        self.assertEqual(row["service_name"], "Haircut")
        self.assertEqual(row["service_minutes"], 45)
        self.assertEqual(row["staff_member_id"], self.online.pk)
        self.assertEqual(row["staff_name"], "Online Stylist")
        self.assertTrue(row["online_bookable"])
        self.assertEqual(row["date"], MONDAY.isoformat())
        self.assertEqual(row["interval_start"], at(MONDAY, 9).isoformat())
        self.assertEqual(row["interval_end"], at(MONDAY, 17).isoformat())
        self.assertEqual(row["interval_minutes"], 480)
        text = export_bookable_slots_csv(self.salon, self.service, MONDAY)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(
            [r["interval_start"] for r in parsed],
            [r["interval_start"] for r in records],
        )

    def test_toggle_off_staff_never_exports(self):
        records = export_bookable_slots(self.salon, self.service, MONDAY)
        self.assertEqual(
            {r["staff_member_id"] for r in records}, {self.online.pk})

    def test_appointment_splits_interval_into_two_rows(self):
        Appointment.objects.create(
            client=self.client, staff_member=self.online,
            service=self.service, start=at(MONDAY, 11), end=at(MONDAY, 11, 45),
        )
        records = export_bookable_slots(self.salon, self.service, MONDAY)
        self.assertEqual(
            [(r["interval_start"], r["interval_end"]) for r in records],
            [(at(MONDAY, 9).isoformat(), at(MONDAY, 11).isoformat()),
             (at(MONDAY, 11, 45).isoformat(), at(MONDAY, 17).isoformat())],
        )

    def test_interval_shorter_than_service_exports_no_rows(self):
        long_service = Service.objects.create(
            category=self.service.category, name="Long", service_minutes=481)
        self.assertEqual(
            export_bookable_slots(self.salon, long_service, MONDAY), [])

    def test_salon_isolation_and_empty_cases(self):
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        other = StaffMember.objects.create(
            salon=other_salon, display_name="Other Stylist", online_bookable=True)
        RosterPattern.objects.create(
            staff_member=other, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))
        records = export_bookable_slots(self.salon, self.service, MONDAY)
        self.assertTrue(records)
        self.assertTrue(all(r["salon_id"] == self.salon.pk for r in records))
        tuesday = MONDAY + datetime.timedelta(days=1)
        for args in ((self.salon, self.service, tuesday),
                     (None, self.service, MONDAY),
                     (self.salon, None, MONDAY),
                     (self.salon, self.service, None)):
            self.assertEqual(export_bookable_slots(*args), [])
            text = export_bookable_slots_csv(*args)
            self.assertEqual(
                text.strip().splitlines(), [",".join(EXPORT_FIELDNAMES)])

    def test_export_is_read_only(self):
        export_bookable_slots(self.salon, self.service, MONDAY)
        export_bookable_slots_csv(self.salon, self.service, MONDAY)
        self.assertEqual(Appointment.objects.count(), 0)
