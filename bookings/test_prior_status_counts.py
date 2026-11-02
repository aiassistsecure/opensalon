import csv, datetime, io  # noqa: E401
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.prior_status_counts import prior_status_counts_report
from bookings.prior_status_counts_export import (
    PRIOR_STATUS_COUNTS_EXPORT_FIELDNAMES, export_prior_status_counts_csv,
    export_prior_status_counts_dict)
from bookings.status_counts import appointment_status_counts
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # Monday, current window
PRIOR_DAY = DAY - datetime.timedelta(days=1)
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class PriorStatusCountsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)

    def _appt(self, day, hour, status):
        return Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=self.service,
            start=at(day, hour), end=at(day, hour) + datetime.timedelta(minutes=45),
            status=status)

    def _book(self):
        S = Appointment.Status
        # Prior: total 4 — booked 1, completed 2, no_show 1.
        self._appt(PRIOR_DAY, 9, S.BOOKED)
        self._appt(PRIOR_DAY, 10, S.COMPLETED)
        self._appt(PRIOR_DAY, 11, S.COMPLETED)
        self._appt(PRIOR_DAY, 12, S.NO_SHOW)
        # Current: total 6 — booked 2, completed 1, cancelled 1,
        # no_show 2.
        self._appt(DAY, 9, S.BOOKED)
        self._appt(DAY, 10, S.BOOKED)
        self._appt(DAY, 11, S.COMPLETED)
        self._appt(DAY, 12, S.CANCELLED)
        self._appt(DAY, 13, S.NO_SHOW)
        self._appt(DAY, 14, S.NO_SHOW)

    def test_salon_deltas_windows_and_verbatim(self):
        self._book()
        r = prior_status_counts_report(self.salon, DAY, DAY)
        self.assertEqual((r.start_date, r.end_date), (DAY, DAY))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR_DAY, PRIOR_DAY))
        self.assertEqual(r.days, 1)
        self.assertEqual(r.current, appointment_status_counts(self.salon, DAY, DAY))
        self.assertEqual(r.prior, appointment_status_counts(self.salon, PRIOR_DAY, PRIOR_DAY))
        self.assertEqual((r.total.current, r.total.prior, r.total.delta,
                          r.total.percent_change), (6, 4, 2, Decimal("50.00")))
        self.assertEqual((r.booked.current, r.booked.prior, r.booked.delta,
                          r.booked.percent_change), (2, 1, 1, Decimal("100.00")))
        self.assertEqual((r.completed.current, r.completed.prior,
                          r.completed.delta, r.completed.percent_change),
                         (1, 2, -1, Decimal("-50.00")))
        self.assertEqual((r.no_show.current, r.no_show.prior, r.no_show.delta),
                         (2, 1, 1))
        # Zero prior -> percent_change None; every status present.
        self.assertEqual(r.cancelled.current, 1)
        self.assertIsNone(r.cancelled.percent_change)
        self.assertEqual(set(r.by_status), {v for v, _ in Appointment.Status.choices})
        self.assertEqual(r.by_status["confirmed"].current, 0)
        self.assertEqual(r["booked"], r.booked)
        self.assertEqual(r.count_for("completed"), r.completed)
        self.assertEqual(r.as_dict()["by_status"]["booked"]["delta"], 1)
        self.assertEqual(r.as_dict()["total"]["percent_change"], Decimal("50.00"))

    def test_equal_length_week_and_aliases(self):
        self._book()
        start = DAY - datetime.timedelta(days=6)
        r = prior_status_counts_report(self.salon, start_date=start, end_date=DAY)
        self.assertEqual(r.days, 7)
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (start - datetime.timedelta(days=7),
                          start - datetime.timedelta(days=1)))
        self.assertEqual(prior_status_counts_report(self.salon, DAY).total.current, 6)

    def test_empty_and_reversed(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        r = prior_status_counts_report(other, DAY, DAY)
        self.assertEqual((r.total.current, r.total.prior, r.total.delta), (0, 0, 0))
        self.assertIsNone(r.total.percent_change)
        self.assertTrue(all(m.current == 0 for m in r.by_status.values()))
        with self.assertRaises(ValueError):
            prior_status_counts_report(self.salon, NEXT, DAY)
        with self.assertRaises(ValueError):
            export_prior_status_counts_csv(self.salon, NEXT, DAY)
        with self.assertRaises(ValueError):
            prior_status_counts_report(self.salon)

    def test_export_csv_and_dict(self):
        self._book()
        text = export_prior_status_counts_csv(self.salon, DAY, DAY)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         PRIOR_STATUS_COUNTS_EXPORT_FIELDNAMES)
        rows = list(csv.DictReader(io.StringIO(text)))
        # 1 total row + one row per status.
        self.assertEqual(len(rows), 1 + len(Appointment.Status.choices))
        self.assertEqual(rows[0]["status"], "total")
        self.assertEqual((rows[0]["current_count"], rows[0]["prior_count"],
                          rows[0]["delta"], rows[0]["percent_change"]),
                         ("6", "4", "2", "50.00"))
        self.assertEqual(rows[0]["prior_end_date"], PRIOR_DAY.isoformat())
        cancelled = [x for x in rows if x["status"] == "cancelled"][0]
        self.assertEqual(cancelled["percent_change"], "")
        d = export_prior_status_counts_dict(self.salon, DAY, DAY)
        self.assertEqual(d["total"]["current"], 6)
        self.assertEqual(d["by_status"]["no_show"]["prior"], 1)
        self.assertEqual(d["rows"][0]["status"], "total")
        self.assertEqual(d["rows"][0]["percent_change"], Decimal("50.00"))

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_status_counts", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_status_counts_csv(self.salon, DAY, DAY))
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start_date=DAY, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date=NEXT, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date="not-a-date", end_date=DAY),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_status_counts", stdout=io.StringIO(), **kwargs)
        m = mock.mock_open()
        with mock.patch("bookings.management.commands.export_prior_status_counts.open", m):
            call_command("export_prior_status_counts", salon_id=self.salon.pk,
                         start_date="2026-11-02", end_date="2026-11-02",
                         output="out.csv")
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertIn("total", written)
