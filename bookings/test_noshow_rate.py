import csv
import datetime
import io
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.noshow_rate import noshow_rate_report
from bookings.noshow_rate_export import export_noshow_rate_csv
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 10, 26)
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class NoShowRateTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)

    def _appt(self, start, status, *, updated=None, **kw):
        a = Appointment.objects.create(
            client=kw.pop("client", self.client),
            staff_member=kw.pop("staff_member", self.staff),
            service=self.service, start=start,
            end=start + datetime.timedelta(minutes=45), status=status, **kw)
        if updated is not None:
            Appointment.objects.filter(pk=a.pk).update(updated_at=updated)
        return a

    def _book(self):
        S = Appointment.Status
        self._appt(at(DAY, 9), S.COMPLETED)
        self._appt(at(DAY, 10), S.COMPLETED)
        self._appt(at(DAY, 11), S.NO_SHOW)
        self._appt(at(DAY, 12), S.BOOKED)
        # Late: cancelled after its start time.
        self._appt(at(DAY, 13), S.CANCELLED, updated=at(DAY, 14))
        # Early: cancelled before its start time — not late.
        self._appt(at(DAY, 15), S.CANCELLED, updated=at(DAY, 13))

    def test_counts_and_decimal_percent_rates(self):
        self._book()
        r = noshow_rate_report(self.salon, DAY, DAY)
        self.assertEqual(r.total_appointments, 6)
        self.assertEqual((r.total, r.completed, r.completed_count), (6, 2, 2))
        self.assertEqual((r.no_shows, r.no_show_count), (1, 1))
        self.assertEqual((r.cancelled, r.cancelled_count), (2, 2))
        self.assertEqual((r.late_cancellations, r.late_cancel_count), (1, 1))
        self.assertIsInstance(r.no_show_rate_percent, Decimal)
        self.assertEqual(r.no_show_rate_percent, Decimal("16.67"))
        self.assertEqual(r.late_cancel_rate_percent, Decimal("16.67"))
        self.assertEqual(r.no_show_rate, r.no_show_rate_percent)
        self.assertEqual(r.as_dict()["late_cancellations"], 1)

    def test_empty_window_rates_are_none(self):
        r = noshow_rate_report(self.salon, DAY, DAY)
        self.assertEqual(r.total_appointments, 0)
        self.assertIsNone(r.no_show_rate_percent)
        self.assertIsNone(r.late_cancel_rate_percent)

    def test_reversed_window_raises_value_error(self):
        with self.assertRaises(ValueError):
            noshow_rate_report(self.salon, NEXT, DAY)
        with self.assertRaises(ValueError):
            export_noshow_rate_csv(self.salon, NEXT, DAY)

    def test_window_and_salon_scoping(self):
        self._book()
        self._appt(at(NEXT, 9), Appointment.Status.NO_SHOW)
        other = Salon.objects.create(name="Other", timezone="UTC")
        os_ = StaffMember.objects.create(salon=other, display_name="Other")
        oc = Client.objects.create(salon=other, first_name="O", last_name="C")
        self._appt(at(DAY, 9), Appointment.Status.NO_SHOW,
                   client=oc, staff_member=os_)
        r = noshow_rate_report(self.salon, DAY, DAY)
        self.assertEqual((r.total_appointments, r.no_shows), (6, 1))
        r2 = noshow_rate_report(self.salon, DAY, NEXT)
        self.assertEqual((r2.total_appointments, r2.no_shows), (7, 2))

    def test_single_day_and_alias_kwargs(self):
        self._book()
        self.assertEqual(noshow_rate_report(self.salon, DAY).total, 6)
        r = noshow_rate_report(self.salon, start_date=DAY, end_date=DAY)
        self.assertEqual(r.total, 6)

    def test_export_csv_matches_service(self):
        self._book()
        rows = list(csv.DictReader(io.StringIO(
            export_noshow_rate_csv(self.salon, DAY, DAY))))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["total_appointments"], "6")
        self.assertEqual(row["completed"], "2")
        self.assertEqual(row["no_shows"], "1")
        self.assertEqual(row["late_cancellations"], "1")
        self.assertEqual(row["no_show_rate_percent"], "16.67")
        self.assertEqual(row["late_cancel_rate_percent"], "16.67")
        empty = list(csv.DictReader(io.StringIO(
            export_noshow_rate_csv(self.salon, NEXT, NEXT))))
        self.assertEqual(empty[0]["no_show_rate_percent"], "")

    def test_command_stdout_matches_export_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_noshow_rate", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_noshow_rate_csv(self.salon, DAY, DAY))
        with self.assertRaises(CommandError):
            call_command("export_noshow_rate",
                         salon_id=self.salon.pk + 1000,
                         date_from=DAY, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_noshow_rate", salon_id=self.salon.pk,
                         date_from=NEXT, date_to=DAY, stdout=io.StringIO())
