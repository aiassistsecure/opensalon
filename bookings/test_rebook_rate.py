import csv
import datetime
import io
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.rebook_rate import rebook_rate_report
from bookings.rebook_rate_export import export_rebook_rate_csv
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 10, 26)
NEXT = DAY + datetime.timedelta(days=1)
LATER = DAY + datetime.timedelta(days=7)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class RebookRateTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)

    def _client(self, name):
        return Client.objects.create(
            salon=self.salon, first_name=name, last_name="Example")

    def _appt(self, client, start, status, *, staff_member=None):
        return Appointment.objects.create(
            client=client, staff_member=staff_member or self.staff,
            service=self.service, start=start,
            end=start + datetime.timedelta(minutes=45), status=status)

    def _book(self):
        S = Appointment.Status
        a, b = self._client("A"), self._client("B")
        c, d, e = self._client("C"), self._client("D"), self._client("E")
        self._appt(a, at(DAY, 9), S.COMPLETED)
        self._appt(a, at(NEXT, 9), S.BOOKED, staff_member=self.staff2)
        self._appt(b, at(DAY, 10), S.COMPLETED)
        self._appt(b, at(LATER, 10), S.CANCELLED)  # cancelled: not a rebook
        self._appt(c, at(DAY, 11), S.COMPLETED, staff_member=self.staff2)
        self._appt(c, at(LATER, 11), S.COMPLETED, staff_member=self.staff2)
        self._appt(d, at(DAY, 12), S.BOOKED)  # not completed: no denominator
        self._appt(e, at(DAY, 13), S.COMPLETED, staff_member=self.staff2)
        # Non-cancelled (no-show) later still counts per the definition.
        self._appt(e, at(LATER, 13), S.NO_SHOW, staff_member=self.staff2)

    def test_counts_per_staff_and_decimal_rate(self):
        self._book()
        r = rebook_rate_report(self.salon, DAY, DAY)
        self.assertEqual((r.total_appointments, r.total), (5, 5))
        self.assertEqual((r.completed, r.completed_count, r.denominator), (4, 4, 4))
        self.assertEqual((r.rebooked, r.rebooked_count), (3, 3))
        self.assertIsInstance(r.rebook_rate_percent, Decimal)
        self.assertEqual(r.rebook_rate_percent, Decimal("75.00"))
        self.assertEqual(r.rebook_rate, r.rebook_rate_percent)
        self.assertEqual(len(r.by_staff), 2)
        one, two = r.by_staff
        self.assertEqual((one.staff_name, one.completed, one.rebooked), ("Stylist One", 2, 1))
        self.assertEqual(one.rebook_rate_percent, Decimal("50.00"))
        self.assertEqual((two.staff_name, two.completed, two.rebooked), ("Stylist Two", 2, 2))
        self.assertEqual(two.rebook_rate_percent, Decimal("100.00"))
        self.assertEqual(r.as_dict()["by_staff"][1]["rebooked"], 2)

    def test_empty_window_rate_is_none(self):
        r = rebook_rate_report(self.salon, DAY, DAY)
        self.assertEqual((r.completed, r.rebooked, r.by_staff), (0, 0, ()))
        self.assertIsNone(r.rebook_rate_percent)

    def test_reversed_window_raises_value_error(self):
        with self.assertRaises(ValueError):
            rebook_rate_report(self.salon, NEXT, DAY)
        with self.assertRaises(ValueError):
            export_rebook_rate_csv(self.salon, NEXT, DAY)

    def test_earlier_and_other_salon_later_do_not_count(self):
        S = Appointment.Status
        a = self._client("A")
        self._appt(a, at(DAY - datetime.timedelta(days=1), 9), S.BOOKED)
        self._appt(a, at(DAY, 9), S.COMPLETED)
        other = Salon.objects.create(name="Other", timezone="UTC")
        os_ = StaffMember.objects.create(salon=other, display_name="Other")
        self._appt(a, at(LATER, 9), S.BOOKED, staff_member=os_)
        r = rebook_rate_report(self.salon, DAY, DAY)
        self.assertEqual((r.completed, r.rebooked), (1, 0))
        self.assertEqual(r.rebook_rate_percent, Decimal("0.00"))

    def test_single_day_and_alias_kwargs(self):
        self._book()
        self.assertEqual(rebook_rate_report(self.salon, DAY).completed, 4)
        r = rebook_rate_report(self.salon, start_date=DAY, end_date=DAY)
        self.assertEqual(r.rebooked, 3)

    def test_export_csv_total_then_per_staff(self):
        self._book()
        rows = list(csv.DictReader(io.StringIO(
            export_rebook_rate_csv(self.salon, DAY, DAY))))
        self.assertEqual(len(rows), 3)
        self.assertEqual((rows[0]["staff_member_id"], rows[0]["staff_name"]), ("", ""))
        self.assertEqual((rows[0]["total_appointments"], rows[0]["completed"],
                          rows[0]["rebooked"], rows[0]["rebook_rate_percent"]),
                         ("5", "4", "3", "75.00"))
        self.assertEqual((rows[2]["staff_name"], rows[2]["rebook_rate_percent"]),
                         ("Stylist Two", "100.00"))
        empty = list(csv.DictReader(io.StringIO(
            export_rebook_rate_csv(self.salon, NEXT, NEXT))))
        self.assertEqual(len(empty), 1)
        self.assertEqual(empty[0]["rebook_rate_percent"], "")

    def test_command_stdout_matches_export_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_rebook_rate", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_rebook_rate_csv(self.salon, DAY, DAY))
        with self.assertRaises(CommandError):
            call_command("export_rebook_rate", salon_id=self.salon.pk + 1000,
                         date_from=DAY, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_rebook_rate", salon_id=self.salon.pk,
                         date_from=NEXT, date_to=DAY, stdout=io.StringIO())
