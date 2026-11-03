"""Tests for the audit-140 staff/now flags on three commands.

export_payroll_feed and export_prior_payroll_feed gain
``--staff-member`` (their services already accept
``staff_member``), and export_noshow gains ``--now`` (its
service already accepts ``now=None``). The payroll services
scope on the StaffMember instance, so the commands resolve
an id to the instance and pass it through verbatim; an
unknown or invalid id raises CommandError. For export_noshow
the ``--now`` value is parsed/coerced exactly like
export_client_history's. Omitted = the previous output
verbatim. Fixtures are tiny synthetic records -- unit logic
only.
"""
import datetime
import io

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment, Break
from bookings.noshow_export import export_noshow_csv
from bookings.payroll_feed_export import export_payroll_feed_csv
from bookings.prior_payroll_feed_export import (
    export_prior_payroll_feed_csv,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import AttendanceRecord, RosterPattern, StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
PRIOR_DAY = DAY - datetime.timedelta(days=1)  # the Sunday before
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


class PayrollFlagsMixin:
    def _make_payroll_fixtures(self):
        self.salon = Salon.objects.create(
            name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        for member in (self.staff, self.staff2):
            for weekday in (0, 6):  # Monday (DAY) + Sunday (prior)
                RosterPattern.objects.create(
                    staff_member=member, weekday=weekday,
                    start_time=datetime.time(9),
                    end_time=datetime.time(17))
            for day in (PRIOR_DAY, DAY):
                AttendanceRecord.objects.create(
                    staff_member=member, event_type="check_in",
                    recorded_at=at(day, 9))
                AttendanceRecord.objects.create(
                    staff_member=member, event_type="check_out",
                    recorded_at=at(day, 17))
        Break.objects.create(
            staff_member=self.staff, start=at(DAY, 12),
            end=at(DAY, 12, 30), paid=True)
        Break.objects.create(
            staff_member=self.staff2, start=at(DAY, 13),
            end=at(DAY, 14), paid=False)


class ExportPayrollFeedStaffFlagTests(PayrollFlagsMixin, TestCase):
    def setUp(self):
        self._make_payroll_fixtures()

    def test_unfiltered_matches_service(self):
        out = io.StringIO()
        call_command("export_payroll_feed", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payroll_feed_csv(self.salon, DAY, DAY))
        self.assertIn("Stylist One", out.getvalue())
        self.assertIn("Stylist Two", out.getvalue())

    def test_filtered_cli_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_payroll_feed", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(),
            "--end-date", DAY.isoformat(),
            "--staff-member", str(self.staff.pk), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payroll_feed_csv(
                self.salon, DAY, DAY, staff_member=self.staff))
        self.assertIn("Stylist One", out.getvalue())
        self.assertNotIn("Stylist Two", out.getvalue())
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_filtered_kwargs_instance_matches_service(self):
        out = io.StringIO()
        call_command("export_payroll_feed", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY,
                     staff_member=self.staff2, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payroll_feed_csv(
                self.salon, DAY, DAY, staff_member=self.staff2))
        self.assertNotIn("Stylist One", out.getvalue())

    def test_filtered_kwargs_id_matches_service(self):
        for value in (self.staff.pk, str(self.staff.pk)):
            out = io.StringIO()
            call_command("export_payroll_feed", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY,
                         staff_member=value, stdout=out)
            self.assertEqual(
                out.getvalue(),
                export_payroll_feed_csv(
                    self.salon, DAY, DAY, staff_member=self.staff))

    def test_other_salon_staff_instance_passes_through(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        outsider = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        out = io.StringIO()
        call_command("export_payroll_feed", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY,
                     staff_member=outsider, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_payroll_feed_csv(
                self.salon, DAY, DAY, staff_member=outsider))

    def test_bad_staff_member_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_payroll_feed", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY,
                         staff_member="not-an-id",
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_payroll_feed", "--salon-id", str(self.salon.pk),
                "--start-date", DAY.isoformat(),
                "--end-date", DAY.isoformat(),
                "--staff-member", "not-an-id", stdout=io.StringIO())

    def test_unknown_staff_member_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_payroll_feed", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY,
                         staff_member=self.staff2.pk + 1000,
                         stdout=io.StringIO())


class ExportPriorPayrollFeedStaffFlagTests(PayrollFlagsMixin, TestCase):
    def setUp(self):
        self._make_payroll_fixtures()

    def test_unfiltered_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_payroll_feed",
                     salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_payroll_feed_csv(self.salon, DAY, DAY))
        self.assertIn("Stylist One", out.getvalue())
        self.assertIn("Stylist Two", out.getvalue())

    def test_filtered_cli_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_prior_payroll_feed",
            "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(),
            "--end-date", DAY.isoformat(),
            "--staff-member", str(self.staff.pk), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_payroll_feed_csv(
                self.salon, DAY, DAY, staff_member=self.staff))
        self.assertIn("Stylist One", out.getvalue())
        self.assertNotIn("Stylist Two", out.getvalue())
        # Header + salon total row + the one scoped staff row.
        self.assertEqual(len(out.getvalue().strip().splitlines()), 3)

    def test_filtered_kwargs_instance_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_payroll_feed",
                     salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY,
                     staff_member=self.staff2, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_payroll_feed_csv(
                self.salon, DAY, DAY, staff_member=self.staff2))
        self.assertNotIn("Stylist One", out.getvalue())

    def test_filtered_kwargs_id_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_payroll_feed",
                     salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY,
                     staff_member=self.staff.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_payroll_feed_csv(
                self.salon, DAY, DAY, staff_member=self.staff))

    def test_bad_staff_member_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_payroll_feed",
                         salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY,
                         staff_member="not-an-id",
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_prior_payroll_feed",
                "--salon-id", str(self.salon.pk),
                "--start-date", DAY.isoformat(),
                "--end-date", DAY.isoformat(),
                "--staff-member", "not-an-id", stdout=io.StringIO())

    def test_unknown_staff_member_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_payroll_feed",
                         salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY,
                         staff_member=self.staff2.pk + 1000,
                         stdout=io.StringIO())


class ExportNoshowNowFlagTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.day = datetime.date(2026, 10, 26)
        Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service,
            start=at(self.day, 11), end=at(self.day, 11, 45),
            status=Appointment.Status.NO_SHOW)

    def test_omitted_now_matches_service_default(self):
        out = io.StringIO()
        call_command("export_noshow", salon_id=self.salon.pk,
                     date_from=self.day, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_noshow_csv(self.salon, self.day, None))

    def test_now_cli_after_appointment_includes_it(self):
        now = at(self.day, 12)
        out = io.StringIO()
        call_command(
            "export_noshow", "--salon-id", str(self.salon.pk),
            "--date-from", self.day.isoformat(),
            "--now", now.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_noshow_csv(self.salon, self.day, None, now=now))
        self.assertIn("no_show", out.getvalue())
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_now_cli_before_appointment_excludes_it(self):
        now = at(self.day, 10)
        out = io.StringIO()
        call_command(
            "export_noshow", "--salon-id", str(self.salon.pk),
            "--date-from", self.day.isoformat(),
            "--now", now.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_noshow_csv(self.salon, self.day, None, now=now))
        self.assertNotIn("no_show", out.getvalue())
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)

    def test_now_cli_z_suffix_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_noshow", "--salon-id", str(self.salon.pk),
            "--date-from", self.day.isoformat(),
            "--now", "2026-10-26T12:00:00Z", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_noshow_csv(
                self.salon, self.day, None, now=at(self.day, 12)))

    def test_now_kwargs_datetime_and_string_match_service(self):
        now = at(self.day, 12)
        for value in (now, now.isoformat()):
            out = io.StringIO()
            call_command("export_noshow", salon_id=self.salon.pk,
                         date_from=self.day, now=value, stdout=out)
            self.assertEqual(
                out.getvalue(),
                export_noshow_csv(
                    self.salon, self.day, None, now=now))

    def test_now_kwargs_date_is_midnight_utc(self):
        midnight = datetime.datetime.combine(
            self.day, datetime.time.min, tzinfo=UTC)
        out = io.StringIO()
        call_command("export_noshow", salon_id=self.salon.pk,
                     date_from=self.day, now=self.day, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_noshow_csv(
                self.salon, self.day, None, now=midnight))
        self.assertNotIn("no_show", out.getvalue())

    def test_bad_now_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_noshow", salon_id=self.salon.pk,
                         date_from=self.day, now="not-a-datetime",
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_noshow", "--salon-id", str(self.salon.pk),
                "--date-from", self.day.isoformat(),
                "--now", "not-a-datetime", stdout=io.StringIO())
