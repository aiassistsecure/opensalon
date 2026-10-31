import csv
import datetime
import io

from django.test import TestCase

from bookings.availability import available_slots
from bookings.availability_export import (
    EXPORT_FIELDNAMES,
    export_available_slots,
    export_available_slots_csv,
)
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class AvailableSlotsExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )

    def _roster(self, staff=None, weekday=0, start=(9, 0), end=(17, 0), **kw):
        return RosterPattern.objects.create(
            staff_member=staff or self.staff, weekday=weekday,
            start_time=datetime.time(*start), end_time=datetime.time(*end), **kw,
        )

    def _appt(self, start_h, end_h, staff=None, **kw):
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=at(MONDAY, start_h),
            end=at(MONDAY, end_h), **kw,
        )

    def test_header_and_fieldnames(self):
        self._roster()
        text = export_available_slots_csv(self.salon, MONDAY)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], EXPORT_FIELDNAMES)
        self.assertEqual(
            EXPORT_FIELDNAMES,
            ["salon_id", "staff_member_id", "staff_name",
             "online_bookable", "start", "end", "minutes"],
        )

    def test_rows_match_service_output(self):
        other = StaffMember.objects.create(
            salon=self.salon, display_name="Another Stylist",
            online_bookable=False,
        )
        self._roster()
        self._roster(staff=other, start=(10, 0), end=(14, 0))
        self._appt(11, 12)
        records = export_available_slots(self.salon, MONDAY)
        expected = [
            {
                "salon_id": self.salon.pk,
                "staff_member_id": entry.staff_member_id,
                "staff_name": entry.staff_member.display_name,
                "online_bookable": entry.online_bookable,
                "start": interval.start.isoformat(),
                "end": interval.end.isoformat(),
                "minutes": interval.minutes,
            }
            for entry in available_slots(self.salon, MONDAY)
            for interval in entry.intervals
        ]
        self.assertEqual(records, expected)
        self.assertEqual(list(records[0].keys()), EXPORT_FIELDNAMES)
        self.assertEqual(
            [(r["staff_name"], r["start"], r["end"], r["minutes"])
             for r in records],
            [("Another Stylist", at(MONDAY, 10).isoformat(),
              at(MONDAY, 14).isoformat(), 240),
             ("Stylist One", at(MONDAY, 9).isoformat(),
              at(MONDAY, 11).isoformat(), 120),
             ("Stylist One", at(MONDAY, 12).isoformat(),
              at(MONDAY, 17).isoformat(), 300)],
        )
        parsed = list(csv.DictReader(io.StringIO(
            export_available_slots_csv(self.salon, MONDAY))))
        self.assertEqual(len(parsed), len(records))
        for row, record in zip(parsed, records):
            self.assertEqual(row, {
                k: ("" if v is None else str(v)) for k, v in record.items()
            })

    def test_cancelled_appointment_does_not_reduce_slots(self):
        self._roster()
        self._appt(11, 12, status=Appointment.Status.CANCELLED)
        records = export_available_slots(self.salon, MONDAY)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["minutes"], 480)

    def test_service_filter_passthrough(self):
        self._roster(end=(12, 0))
        self._appt(10, 11)  # leaves two 60-minute intervals
        long_service = Service.objects.create(
            category=self.service.category, name="Long", service_minutes=90
        )
        self.assertEqual(len(export_available_slots(self.salon, MONDAY)), 2)
        self.assertEqual(
            export_available_slots(self.salon, MONDAY, service=long_service),
            [],
        )
        self.assertEqual(
            len(export_available_slots(
                self.salon, MONDAY, service=self.service)), 2)

    def test_online_only_passthrough_and_default_flag(self):
        other = StaffMember.objects.create(
            salon=self.salon, display_name="Offline", online_bookable=False
        )
        self._roster()
        self._roster(staff=other)
        default = export_available_slots(self.salon, MONDAY)
        self.assertEqual(
            {r["staff_name"]: r["online_bookable"] for r in default},
            {"Stylist One": True, "Offline": False},
        )
        online = export_available_slots(self.salon, MONDAY, online_only=True)
        self.assertEqual([r["staff_name"] for r in online], ["Stylist One"])
        online_csv = export_available_slots_csv(
            self.salon, MONDAY, online_only=True)
        self.assertEqual(
            [r["staff_name"] for r in csv.DictReader(io.StringIO(online_csv))],
            ["Stylist One"],
        )

    def test_empty_and_fully_booked_export_no_rows(self):
        self.assertEqual(export_available_slots(self.salon, MONDAY), [])
        self.assertEqual(export_available_slots(None, MONDAY), [])
        self._roster()
        self._appt(9, 17)
        self.assertEqual(export_available_slots(self.salon, MONDAY), [])
        text = export_available_slots_csv(self.salon, MONDAY)
        self.assertEqual(
            text.strip().splitlines(), [",".join(EXPORT_FIELDNAMES)])

    def test_salon_isolation(self):
        other_salon = Salon.objects.create(name="Other Salon", timezone="UTC")
        outsider = StaffMember.objects.create(
            salon=other_salon, display_name="Outsider")
        self._roster()
        self._roster(staff=outsider)
        records = export_available_slots(self.salon, MONDAY)
        self.assertEqual(
            [r["staff_member_id"] for r in records], [self.staff.pk])
        self.assertTrue(all(r["salon_id"] == self.salon.pk for r in records))

    def test_read_only(self):
        self._roster()
        self._appt(11, 12)
        before = (Appointment.objects.count(), RosterPattern.objects.count(),
                  StaffMember.objects.count())
        export_available_slots(self.salon, MONDAY)
        export_available_slots_csv(self.salon, MONDAY)
        self.assertEqual(
            (Appointment.objects.count(), RosterPattern.objects.count(),
             StaffMember.objects.count()), before)
