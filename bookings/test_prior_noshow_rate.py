import csv, datetime, io  # noqa: E401
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.noshow_rate import noshow_rate_report
from bookings.prior_noshow_rate import prior_noshow_rate_report
from bookings.prior_noshow_rate_export import (
    PRIOR_NOSHOW_RATE_EXPORT_FIELDNAMES, export_prior_noshow_rate_csv)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 10, 26)
PRIOR_DAY = DAY - datetime.timedelta(days=1)
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class PriorNoShowRateTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(category=cat, name="Haircut", service_minutes=45)

    def _appt(self, day, hour, status, *, updated=None):
        a = Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=self.service,
            start=at(day, hour), end=at(day, hour) + datetime.timedelta(minutes=45),
            status=status)
        if updated is not None:
            Appointment.objects.filter(pk=a.pk).update(updated_at=updated)
        return a

    def _book(self):
        S = Appointment.Status
        # Prior: total 4, completed 2, no_shows 1, cancelled 1, late 1,
        # no_show_rate 25.00, late_cancel_rate 25.00.
        self._appt(PRIOR_DAY, 9, S.COMPLETED)
        self._appt(PRIOR_DAY, 10, S.NO_SHOW)
        self._appt(PRIOR_DAY, 11, S.COMPLETED)
        self._appt(PRIOR_DAY, 12, S.CANCELLED, updated=at(PRIOR_DAY, 13))
        # Current: total 6, completed 2, no_shows 2, cancelled 1, late 0,
        # no_show_rate 33.33, late_cancel_rate 0.00.
        self._appt(DAY, 9, S.COMPLETED)
        self._appt(DAY, 10, S.NO_SHOW)
        self._appt(DAY, 11, S.NO_SHOW)
        self._appt(DAY, 12, S.COMPLETED)
        self._appt(DAY, 13, S.CANCELLED, updated=at(DAY, 12))
        self._appt(DAY, 14, S.BOOKED)

    def test_both_windows_verbatim_and_deltas(self):
        self._book()
        r = prior_noshow_rate_report(self.salon, DAY, DAY)
        self.assertEqual((r.start_date, r.end_date), (DAY, DAY))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR_DAY, PRIOR_DAY))
        self.assertEqual(r.days, 1)
        self.assertEqual(r.current, noshow_rate_report(self.salon, DAY, DAY))
        self.assertEqual(r.prior, noshow_rate_report(self.salon, PRIOR_DAY, PRIOR_DAY))
        self.assertEqual((r.total_appointments.current, r.total_appointments.prior,
                          r.total_appointments.delta, r.total_appointments.percent_change),
                         (6, 4, 2, Decimal("50.00")))
        self.assertEqual((r.completed.current, r.completed.prior, r.completed.delta,
                          r.completed.percent_change), (2, 2, 0, Decimal("0.00")))
        self.assertEqual((r.no_shows.current, r.no_shows.prior, r.no_shows.delta,
                          r.no_shows.percent_change), (2, 1, 1, Decimal("100.00")))
        self.assertEqual((r.cancelled.delta, r.late_cancellations.current,
                          r.late_cancellations.prior, r.late_cancellations.delta,
                          r.late_cancellations.percent_change),
                         (0, 0, 1, -1, Decimal("-100.00")))
        self.assertEqual((r.no_show_rate_percent.current, r.no_show_rate_percent.prior,
                          r.no_show_rate_percent.delta, r.no_show_rate_percent.percent_change),
                         (Decimal("33.33"), Decimal("25.00"), Decimal("8.33"), Decimal("33.32")))
        self.assertEqual((r.late_cancel_rate_percent.current, r.late_cancel_rate_percent.prior,
                          r.late_cancel_rate_percent.delta,
                          r.late_cancel_rate_percent.percent_change),
                         (Decimal("0.00"), Decimal("25.00"), Decimal("-25.00"), Decimal("-100.00")))
        self.assertEqual(r.no_show_rate, r.no_show_rate_percent)
        self.assertEqual(r.as_dict()["no_shows"]["delta"], 1)

    def test_none_on_zero_prior(self):
        self._book()
        # Current window DAY+1..DAY+1 is empty; its prior window is DAY,
        # so instead check a salon with no data at all: prior zero.
        other = Salon.objects.create(name="Other", timezone="UTC")
        r = prior_noshow_rate_report(other, DAY, DAY)
        self.assertEqual((r.total_appointments.current, r.total_appointments.prior), (0, 0))
        self.assertIsNone(r.total_appointments.percent_change)
        self.assertIsNone(r.no_shows.percent_change)
        self.assertIsNone(r.no_show_rate_percent.current)
        self.assertIsNone(r.no_show_rate_percent.delta)
        self.assertIsNone(r.no_show_rate_percent.percent_change)
        # Zero-prior count with a non-zero current: percent is None.
        r2 = prior_noshow_rate_report(self.salon, PRIOR_DAY, PRIOR_DAY)
        # Prior of PRIOR_DAY is empty (no bookings before), current has data.
        self.assertEqual(r2.no_shows.prior, 0)
        self.assertIsNone(r2.no_shows.percent_change)
        self.assertIsNone(r2.no_show_rate_percent.percent_change)

    def test_equal_length_week_and_aliases(self):
        self._book()
        start = DAY - datetime.timedelta(days=6)
        r = prior_noshow_rate_report(self.salon, start_date=start, end_date=DAY)
        self.assertEqual(r.days, 7)
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (start - datetime.timedelta(days=7), start - datetime.timedelta(days=1)))
        self.assertEqual(prior_noshow_rate_report(self.salon, DAY).total_appointments.current, 6)

    def test_reversed_raises(self):
        with self.assertRaises(ValueError):
            prior_noshow_rate_report(self.salon, NEXT, DAY)
        with self.assertRaises(ValueError):
            export_prior_noshow_rate_csv(self.salon, NEXT, DAY)

    def test_export_csv(self):
        self._book()
        text = export_prior_noshow_rate_csv(self.salon, DAY, DAY)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         PRIOR_NOSHOW_RATE_EXPORT_FIELDNAMES)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["current_total_appointments"], row["prior_total_appointments"],
                          row["total_appointments_delta"], row["total_appointments_percent_change"]),
                         ("6", "4", "2", "50.00"))
        self.assertEqual((row["current_no_show_rate_percent"], row["prior_no_show_rate_percent"],
                          row["no_show_rate_delta"], row["no_show_rate_percent_change"]),
                         ("33.33", "25.00", "8.33", "33.32"))
        self.assertEqual((row["current_late_cancellations"], row["late_cancel_rate_delta"]),
                         ("0", "-25.00"))
        self.assertEqual(row["prior_end_date"], PRIOR_DAY.isoformat())
        empty = list(csv.DictReader(io.StringIO(
            export_prior_noshow_rate_csv(self.salon, NEXT, NEXT))))
        self.assertEqual(empty[0]["current_no_show_rate_percent"], "")
        self.assertEqual(empty[0]["no_show_rate_percent_change"], "")

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_noshow_rate", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_noshow_rate_csv(self.salon, DAY, DAY))
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start_date=DAY, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date=NEXT, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date="not-a-date", end_date=DAY),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_noshow_rate", stdout=io.StringIO(), **kwargs)
        m = mock.mock_open()
        with mock.patch("bookings.management.commands.export_prior_noshow_rate.open", m):
            call_command("export_prior_noshow_rate", salon_id=self.salon.pk,
                         start_date="2026-10-26", end_date="2026-10-26", output="out.csv")
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertIn("33.33", written)
