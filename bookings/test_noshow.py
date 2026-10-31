import datetime

from django.test import TestCase

from bookings.models import Appointment
from bookings.noshow import (
    list_noshows,
    no_show_report,
    noshow_appointments,
    noshow_report,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class NoShowReportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example",
            email="test@example.com", phone="555-0100")
        self.client2 = Client.objects.create(
            salon=self.salon, first_name="Second", last_name="Client")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)

    def _appt(self, start, status=Appointment.Status.COMPLETED, **kw):
        return Appointment.objects.create(
            client=kw.pop("client", self.client),
            staff_member=kw.pop("staff_member", self.staff),
            service=kw.pop("service", self.service),
            start=start, end=start + datetime.timedelta(minutes=45),
            status=status, **kw)

    def test_empty_range_zero_rate_and_groups(self):
        r = noshow_report(self.salon, DAY, now=NOW)
        self.assertEqual((r.no_show_count, r.count, r.denominator, r.rate), (0, 0, 0, 0.0))
        self.assertEqual((r.by_staff, r.by_client), ((), ()))
        self.assertEqual(r.start_date, DAY)
        self.assertEqual(noshow_appointments(self.salon, DAY, now=NOW), [])

    def test_count_and_rate_exclude_cancelled_and_future(self):
        self._appt(at(DAY, 9), Appointment.Status.NO_SHOW)
        self._appt(at(DAY, 10), Appointment.Status.NO_SHOW)
        self._appt(at(DAY, 11), Appointment.Status.COMPLETED)
        self._appt(at(DAY, 12), Appointment.Status.BOOKED)
        self._appt(at(DAY, 13), Appointment.Status.CANCELLED)
        # Future (after NOW) completed/no-show: excluded entirely.
        future = DAY + datetime.timedelta(days=2)
        self._appt(at(future, 9), Appointment.Status.COMPLETED)
        self._appt(at(future, 10), Appointment.Status.NO_SHOW)
        r = noshow_report(self.salon, DAY, DAY + datetime.timedelta(days=2), now=NOW)
        self.assertEqual(r.no_show_count, 2)
        self.assertEqual(r.denominator, 4)
        self.assertEqual(r.rate, 0.5)

    def test_grouped_by_staff_and_client(self):
        self._appt(at(DAY, 9), Appointment.Status.NO_SHOW)
        self._appt(at(DAY, 10), Appointment.Status.NO_SHOW, client=self.client2)
        self._appt(at(DAY, 11), Appointment.Status.NO_SHOW,
                   staff_member=self.staff2, client=self.client2)
        self._appt(at(DAY, 12), Appointment.Status.COMPLETED,
                   staff_member=self.staff2, client=self.client2)
        r = no_show_report(self.salon, DAY, now=NOW)
        self.assertEqual(r.no_show_count, 3)
        self.assertEqual(r.denominator, 4)
        staff = {s.staff_member_id: s for s in r.by_staff}
        self.assertEqual(staff[self.staff.pk].no_show_count, 2)
        self.assertEqual(staff[self.staff.pk].staff_name, "Stylist One")
        self.assertEqual(staff[self.staff.pk].rate, 1.0)
        self.assertEqual(staff[self.staff2.pk].rate, 0.5)
        # Worst first.
        self.assertEqual(r.by_staff[0].staff_member_id, self.staff.pk)
        clients = {c.client_id: c for c in r.by_client}
        self.assertEqual(clients[self.client2.pk].no_show_count, 2)
        self.assertEqual(clients[self.client2.pk].client_name, "Second Client")
        self.assertEqual(clients[self.client.pk].no_show_count, 1)
        self.assertEqual(r.by_client[0].client_id, self.client2.pk)
        d = r.as_dict()
        self.assertEqual(d["no_show_count"], 3)
        self.assertNotIn("email", str(d))
        self.assertNotIn("555-0100", str(d))

    def test_listing_most_recent_first_no_contact_details(self):
        a = self._appt(at(DAY, 9), Appointment.Status.NO_SHOW)
        b = self._appt(at(DAY, 14), Appointment.Status.NO_SHOW,
                       service=None, service_name="Imported Cut")
        self._appt(at(DAY, 15), Appointment.Status.COMPLETED)
        rows = list_noshows(self.salon, DAY, now=NOW)
        self.assertEqual([row["id"] for row in rows], [b.pk, a.pk])
        self.assertEqual(rows[0]["service_name"], "Imported Cut")
        self.assertEqual(rows[0]["status"], "no_show")
        for row in rows:
            self.assertNotIn("email", row)
            self.assertNotIn("phone", row)
            self.assertNotIn("test@example.com", str(row))

    def test_range_inclusive_other_salon_and_reversed(self):
        nxt = DAY + datetime.timedelta(days=1)
        self._appt(at(DAY, 9), Appointment.Status.NO_SHOW)
        self._appt(at(nxt, 9), Appointment.Status.NO_SHOW)
        self._appt(at(nxt + datetime.timedelta(days=1), 9),
                   Appointment.Status.NO_SHOW)
        other = Salon.objects.create(name="Other", timezone="UTC")
        os_ = StaffMember.objects.create(salon=other, display_name="Other")
        oc = Client.objects.create(salon=other, first_name="O", last_name="C")
        self._appt(at(DAY, 10), Appointment.Status.NO_SHOW,
                   client=oc, staff_member=os_)
        r = noshow_report(self.salon, DAY, nxt, now=NOW + datetime.timedelta(days=2))
        self.assertEqual(r.no_show_count, 2)
        rev = noshow_report(self.salon, nxt, DAY, now=NOW)
        self.assertEqual((rev.no_show_count, rev.denominator, rev.rate), (0, 0, 0.0))
        self.assertEqual(noshow_report(None, DAY, now=NOW).no_show_count, 0)
        self.assertEqual(noshow_appointments(None, DAY, now=NOW), [])

    def test_exactly_now_is_not_past(self):
        self._appt(NOW, Appointment.Status.NO_SHOW)
        self._appt(NOW, Appointment.Status.COMPLETED)
        r = noshow_report(self.salon, DAY, DAY + datetime.timedelta(days=1), now=NOW)
        self.assertEqual((r.no_show_count, r.denominator), (0, 0))

    def test_read_only_nothing_mutated(self):
        self._appt(at(DAY, 9), Appointment.Status.NO_SHOW)
        before = Appointment.objects.count()
        noshow_report(self.salon, DAY, now=NOW)
        noshow_appointments(self.salon, DAY, now=NOW)
        self.assertEqual(Appointment.objects.count(), before)
