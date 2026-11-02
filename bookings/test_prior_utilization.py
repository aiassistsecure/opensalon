import csv, datetime, io  # noqa: E401
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.prior_utilization import prior_utilization_report
from bookings.prior_utilization_export import (
    PRIOR_UTILIZATION_EXPORT_FIELDNAMES, export_prior_utilization_csv)
from bookings.utilization import staff_utilization
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MON = datetime.date(2026, 11, 2)  # Monday, current window
SUN = MON - datetime.timedelta(days=1)  # Sunday, prior window
TUE = MON + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class PriorUtilizationTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.staff3 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Three")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)

    def _pattern(self, staff, weekday, end_hour=17):
        return RosterPattern.objects.create(
            staff_member=staff, weekday=weekday,
            start_time=datetime.time(9), end_time=datetime.time(end_hour))

    def _appt(self, day, start_hour, end_hour, staff=None):
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.staff,
            service=self.service, start=at(day, start_hour),
            end=at(day, end_hour))

    def _book(self):
        # Roster: One Sun+Mon 9-17 (480/day); Two Sun+Mon 9-13 (240/day).
        for staff, end in ((self.staff, 17), (self.staff2, 13)):
            self._pattern(staff, 6, end)
            self._pattern(staff, 0, end)
        # Prior (Sun): One 1 appt / 240 booked; Two none.
        self._appt(SUN, 9, 13)
        # Current (Mon): One 2 appts / 360 booked; Two 1 appt / 120.
        self._appt(MON, 9, 12)
        self._appt(MON, 13, 16)
        self._appt(MON, 9, 11, staff=self.staff2)
        # Prior totals: count 1, booked 240, rostered 720, util 1/3.
        # Current totals: count 3, booked 480, rostered 720, util 2/3.

    def test_salon_deltas_and_windows(self):
        self._book()
        r = prior_utilization_report(self.salon, MON, MON)
        self.assertEqual((r.start_date, r.end_date), (MON, MON))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (SUN, SUN))
        self.assertEqual(r.days, 1)
        self.assertEqual(r.current, staff_utilization(self.salon, MON, MON))
        self.assertEqual(r.prior, staff_utilization(self.salon, SUN, SUN))
        self.assertEqual((r.appointment_count.current, r.appointment_count.prior,
                          r.appointment_count.delta,
                          r.appointment_count.percent_change),
                         (3, 1, 2, Decimal("200.00")))
        self.assertEqual((r.booked_minutes.current, r.booked_minutes.prior,
                          r.booked_minutes.delta,
                          r.booked_minutes.percent_change),
                         (480, 240, 240, Decimal("100.00")))
        self.assertEqual((r.rostered_minutes.delta,
                          r.rostered_minutes.percent_change),
                         (0, Decimal("0.00")))
        self.assertAlmostEqual(r.utilization.current, 2 / 3)
        self.assertAlmostEqual(r.utilization.prior, 1 / 3)
        self.assertAlmostEqual(r.utilization.delta, 1 / 3)
        self.assertEqual(r.utilization.percent_change, Decimal("100.00"))
        self.assertAlmostEqual(r.current_utilization, 2 / 3)
        self.assertAlmostEqual(r.prior_utilization, 1 / 3)
        self.assertEqual(r.as_dict()["booked_minutes"]["delta"], 240)

    def test_per_staff_rows_and_zero_staff(self):
        self._book()
        r = prior_utilization_report(self.salon, MON, MON)
        self.assertEqual([s.staff_name for s in r.by_staff],
                         ["Stylist One", "Stylist Three", "Stylist Two"])
        one, three, two = r.by_staff
        self.assertEqual((one.appointment_count.current,
                          one.appointment_count.prior), (2, 1))
        self.assertAlmostEqual(one.utilization.current, 0.75)
        self.assertAlmostEqual(one.utilization.prior, 0.5)
        self.assertAlmostEqual(one.utilization.delta, 0.25)
        self.assertEqual(one.utilization.percent_change, Decimal("50.00"))
        self.assertEqual((two.booked_minutes.current, two.booked_minutes.prior),
                         (120, 0))
        self.assertIsNone(two.booked_minutes.percent_change)  # zero prior
        self.assertAlmostEqual(two.utilization.current, 0.5)
        self.assertIsNone(two.utilization.percent_change)  # prior util 0
        self.assertEqual((three.appointment_count.current,
                          three.rostered_minutes.current), (0, 0))
        self.assertEqual(three.utilization.current, 0.0)
        self.assertEqual(three.utilization.delta, 0.0)
        self.assertIsNone(three.utilization.percent_change)

    def test_equal_length_week_and_aliases(self):
        self._book()
        start = MON - datetime.timedelta(days=6)
        r = prior_utilization_report(self.salon, start_date=start, end_date=MON)
        self.assertEqual(r.days, 7)
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (start - datetime.timedelta(days=7),
                          start - datetime.timedelta(days=1)))
        self.assertEqual(
            prior_utilization_report(self.salon, MON).appointment_count.current, 3)

    def test_empty_and_reversed(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        r = prior_utilization_report(other, MON, MON)
        self.assertEqual((r.appointment_count.current, r.by_staff), (0, ()))
        self.assertEqual(r.utilization.current, 0.0)
        self.assertEqual(r.utilization.delta, 0.0)
        self.assertIsNone(r.utilization.percent_change)
        self.assertIsNone(r.booked_minutes.percent_change)
        with self.assertRaises(ValueError):
            prior_utilization_report(self.salon, TUE, MON)
        with self.assertRaises(ValueError):
            export_prior_utilization_csv(self.salon, TUE, MON)
        with self.assertRaises(ValueError):
            prior_utilization_report(self.salon)

    def test_export_csv_total_then_per_staff(self):
        self._book()
        text = export_prior_utilization_csv(self.salon, MON, MON)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         PRIOR_UTILIZATION_EXPORT_FIELDNAMES)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 4)
        self.assertEqual((rows[0]["staff_member_id"], rows[0]["staff_name"]), ("", ""))
        self.assertEqual((rows[0]["current_appointment_count"],
                          rows[0]["prior_appointment_count"],
                          rows[0]["appointment_count_delta"],
                          rows[0]["current_booked_minutes"],
                          rows[0]["booked_minutes_percent_change"]),
                         ("3", "1", "2", "480", "100.00"))
        self.assertEqual((rows[0]["current_utilization"],
                          rows[0]["prior_utilization"],
                          rows[0]["utilization_delta"],
                          rows[0]["utilization_percent_change"]),
                         ("0.6667", "0.3333", "0.3333", "100.00"))
        self.assertEqual(rows[0]["prior_end_date"], SUN.isoformat())
        two = [x for x in rows if x["staff_name"] == "Stylist Two"][0]
        self.assertEqual(two["booked_minutes_percent_change"], "")
        self.assertEqual(two["current_utilization"], "0.5000")

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_utilization", salon_id=self.salon.pk,
                     start_date=MON, end_date=MON, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_utilization_csv(self.salon, MON, MON))
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start_date=MON, end_date=MON),
                       dict(salon_id=self.salon.pk, start_date=TUE, end_date=MON),
                       dict(salon_id=self.salon.pk, start_date="not-a-date", end_date=MON),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_utilization", stdout=io.StringIO(), **kwargs)
        m = mock.mock_open()
        with mock.patch("bookings.management.commands.export_prior_utilization.open", m):
            call_command("export_prior_utilization", salon_id=self.salon.pk,
                         start_date="2026-11-02", end_date="2026-11-02",
                         output="out.csv")
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertIn("0.6667", written)
