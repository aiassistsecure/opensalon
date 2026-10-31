import datetime

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.cancellations import online_cancellation_summary
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
D1 = datetime.date(2026, 11, 2)
D2 = datetime.date(2026, 11, 3)
D3 = datetime.date(2026, 11, 4)


def at(day, hour=10):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class OnlineCancellationSummaryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Beth")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)
        self.service2 = Service.objects.create(
            category=cat, name="Colour", service_minutes=60)

    def _appt(self, day=D1, staff=None, service="default", status="cancelled",
              origin="online", **kw):
        svc = self.service if service == "default" else service
        return Appointment.objects.create(
            client=kw.pop("client", self.client),
            staff_member=staff or self.staff, service=svc,
            start=at(day, kw.pop("hour", 10)),
            end=at(day, kw.pop("end_hour", 11)),
            status=status, origin=origin, **kw)

    def test_total_by_staff_service_day(self):
        self._appt(D1)
        self._appt(D1, service=self.service2)
        self._appt(D2, staff=self.staff2)
        r = online_cancellation_summary(self.salon, D1, D3)
        self.assertEqual((r.total, r.total_count, r.count), (3, 3, 3))
        self.assertEqual((r.start_date, r.end_date), (D1, D3))
        self.assertEqual(
            [(s.staff_member_id, s.staff_display_name, s.count)
             for s in r.by_staff],
            [(self.staff.pk, "Alice", 2), (self.staff2.pk, "Beth", 1)])
        self.assertEqual(r.count_for_staff(self.staff), 2)
        self.assertEqual(
            [(s.service_name, s.count) for s in r.by_service],
            [("Haircut", 2), ("Colour", 1)])
        self.assertEqual([(d.date, d.count) for d in r.by_day],
                         [(D1, 2), (D2, 1), (D3, 0)])
        self.assertEqual(r.count_for_day(D2), 1)
        self.assertEqual(r.by_date, r.by_day)

    def test_excludes_non_online_non_cancelled_and_out_of_range(self):
        self._appt(D1)
        self._appt(D1, origin="phone")
        self._appt(D1, origin="walk_in")
        self._appt(D1, origin="unknown")
        self._appt(D1, status="booked")
        self._appt(D1, status="completed")
        self._appt(D1, status="no_show")
        self._appt(datetime.date(2026, 11, 1))
        self._appt(D3)
        r = online_cancellation_summary(self.salon, D1, D2)
        self.assertEqual(r.total, 1)

    def test_service_name_snapshot_fallback(self):
        self._appt(D1, service=None, service_name="Snapshot Cut")
        self._appt(D1, service=None, service_name="Snapshot Cut")
        self._appt(D1, service=None, service_name="")
        r = online_cancellation_summary(self.salon, D1)
        self.assertEqual(r.total, 3)
        self.assertEqual(
            [(s.service_id, s.service_name, s.count) for s in r.by_service],
            [(None, "Snapshot Cut", 2), (None, "", 1)])

    def test_other_salon_excluded(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        o_staff = StaffMember.objects.create(salon=other, display_name="O")
        o_client = Client.objects.create(
            salon=other, first_name="O", last_name="X")
        self._appt(D1, staff=o_staff, client=o_client)
        # Staff in salon but client elsewhere also excluded.
        self._appt(D1, client=o_client)
        self._appt(D1)
        r = online_cancellation_summary(self.salon, D1, D2)
        self.assertEqual(r.total, 1)

    def test_none_salon_reversed_and_empty(self):
        self.assertEqual(online_cancellation_summary(None, D1, D2).total, 0)
        r = online_cancellation_summary(self.salon, D2, D1)
        self.assertEqual(r.total, 0)
        self.assertEqual(r.by_staff, ())
        empty = online_cancellation_summary(self.salon, D1, D2)
        self.assertEqual(empty.total, 0)
        self.assertEqual([(d.date, d.count) for d in empty.by_day],
                         [(D1, 0), (D2, 0)])
        self.assertEqual(empty.as_dict()["total"], 0)

    def test_day_judged_in_salon_timezone(self):
        salon = Salon.objects.create(
            name="NY", timezone="America/New_York")
        staff = StaffMember.objects.create(salon=salon, display_name="NY S")
        client = Client.objects.create(
            salon=salon, first_name="N", last_name="Y")
        # 01:00 UTC on D2 is 20:00 EST on D1.
        Appointment.objects.create(
            client=client, staff_member=staff, service=self.service,
            start=at(D2, 1), end=at(D2, 2),
            status="cancelled", origin="online")
        self.assertEqual(
            online_cancellation_summary(salon, D1, D1).total, 1)
        self.assertEqual(
            online_cancellation_summary(salon, D2, D2).total, 0)

    def test_kwargs_and_as_dict(self):
        self._appt(D1)
        r = online_cancellation_summary(
            self.salon, date_from=D1, date_to=D2)
        d = r.as_dict()
        self.assertEqual(d["total"], 1)
        self.assertEqual(d["by_staff"][0]["staff_display_name"], "Alice")
        self.assertEqual(d["by_service"][0]["service_name"], "Haircut")
        self.assertEqual(d["by_day"][0], {"date": D1.isoformat(), "count": 1})
        self.assertEqual(r.counts_by_service, {"Haircut": 1})

    def test_read_only(self):
        self._appt(D1)
        before = Appointment.objects.count()
        online_cancellation_summary(self.salon, D1, D3)
        self.assertEqual(Appointment.objects.count(), before)
        self.assertEqual(
            Appointment.objects.get().status, "cancelled")
