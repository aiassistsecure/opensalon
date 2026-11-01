import datetime

from django.test import TestCase

from bookings.models import Appointment
from bookings.utilization import staff_utilization, utilization_report
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, ShiftOverride, StaffMember

MON = datetime.date(2026, 11, 2)  # Monday
TUE = datetime.date(2026, 11, 3)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class StaffUtilizationTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)

    def _appt(self, start, end, staff=None, **kw):
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=start, end=end, **kw)

    def _pattern(self, staff=None, weekday=0, start=(9, 0), end=(17, 0)):
        return RosterPattern.objects.create(
            staff_member=staff or self.staff, weekday=weekday,
            start_time=datetime.time(*start), end_time=datetime.time(*end))

    def test_single_day_booked_over_rostered(self):
        self._pattern()  # 480 rostered Mon
        self._appt(at(MON, 9), at(MON, 13))  # 240 booked
        report = staff_utilization(self.salon, MON)
        (row,) = report.by_staff
        self.assertEqual(row.staff_member, self.staff)
        self.assertEqual(row.staff_member_id, self.staff.pk)
        self.assertEqual(row.display_name, "Stylist One")
        self.assertEqual((row.appointment_count, row.booked_minutes), (1, 240))
        self.assertEqual(row.rostered_minutes, 480)
        self.assertEqual(row.utilization, 0.5)
        self.assertEqual(report.booked_minutes, 240)
        self.assertEqual(report.rostered_minutes, 480)
        self.assertEqual(report.utilization, 0.5)
        self.assertEqual((report.start_date, report.end_date), (MON, MON))

    def test_range_sums_days_and_excludes_cancelled(self):
        self._pattern(weekday=0)
        self._pattern(weekday=1)
        self._appt(at(MON, 9), at(MON, 10))
        self._appt(at(TUE, 9), at(TUE, 11))
        self._appt(at(TUE, 13), at(TUE, 14), status=Appointment.Status.CANCELLED)
        report = utilization_report(self.salon, MON, TUE)
        (row,) = report.by_staff
        self.assertEqual((row.appointment_count, row.booked_minutes), (2, 180))
        self.assertEqual(row.rostered_minutes, 960)
        self.assertAlmostEqual(row.utilization, 180 / 960)

    def test_zero_rostered_is_safe_with_and_without_bookings(self):
        other = StaffMember.objects.create(
            salon=self.salon, display_name="Another Stylist")
        self._appt(at(MON, 9), at(MON, 10))  # booked, no roster pattern
        report = staff_utilization(self.salon, MON)
        by_name = {r.display_name: r for r in report.by_staff}
        self.assertEqual(by_name["Stylist One"].rostered_minutes, 0)
        self.assertEqual(by_name["Stylist One"].booked_minutes, 60)
        self.assertEqual(by_name["Stylist One"].utilization, 0.0)
        self.assertEqual(by_name["Another Stylist"].utilization, 0.0)
        self.assertEqual(report.utilization, 0.0)
        self.assertEqual(other.display_name, "Another Stylist")

    def test_overbooked_can_exceed_one(self):
        self._pattern(end=(10, 0))  # 60 rostered
        self._appt(at(MON, 9), at(MON, 11))  # 120 booked
        (row,) = staff_utilization(self.salon, MON).by_staff
        self.assertEqual(row.utilization, 2.0)

    def test_shift_override_rules_its_date(self):
        self._pattern()  # Mon 9-17 pattern
        ShiftOverride.objects.create(
            staff_member=self.staff, date=MON, is_off=True)
        (row,) = staff_utilization(self.salon, MON).by_staff
        self.assertEqual(row.rostered_minutes, 0)
        self.assertEqual(row.utilization, 0.0)

    def test_inactive_and_other_salon_excluded_reversed_empty(self):
        StaffMember.objects.create(
            salon=self.salon, display_name="Inactive", active=False)
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        StaffMember.objects.create(salon=other_salon, display_name="Other")
        report = staff_utilization(self.salon, MON)
        self.assertEqual([r.display_name for r in report.by_staff],
                         ["Stylist One"])
        reversed_report = staff_utilization(self.salon, TUE, MON)
        self.assertEqual(reversed_report.by_staff, ())
        self.assertEqual(reversed_report.utilization, 0.0)
        self.assertEqual(staff_utilization(None, MON).by_staff, ())
