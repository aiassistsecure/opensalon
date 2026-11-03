"""Tests for --staff-member on the breaks-family export commands.

export_breaks, export_break_totals and export_prior_break_totals
gain the staff filter their services already accept
(``staff_member=None``). Resolution mirrors
export_appointment_search: an id (or a StaffMember instance via
call_command kwargs) is coerced to its pk and passed through
unchanged; salon scoping is the services' own
(``staff_member__salon``), so another salon's staff id exports
nothing. Omitted = the previous salon-wide output verbatim.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io

from django.core.management import call_command
from django.test import TestCase

from bookings.break_totals_export import export_break_totals_csv
from bookings.breaks_export import export_breaks_csv
from bookings.models import Break
from bookings.prior_break_totals_export import export_prior_break_totals_csv
from saloncore.models import Salon
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
PRIOR_DAY = DAY - datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


class BreaksStaffFilterCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist")
        for day in (PRIOR_DAY, DAY):
            Break.objects.create(
                staff_member=self.staff, start=at(day, 12),
                end=at(day, 12, 30), paid=True)
            Break.objects.create(
                staff_member=self.staff2, start=at(day, 13),
                end=at(day, 14), paid=False)
        Break.objects.create(
            staff_member=self.other_staff, start=at(DAY, 12),
            end=at(DAY, 13), paid=True)

    # -- export_breaks -------------------------------------------------
    def test_breaks_unfiltered_matches_service(self):
        out = io.StringIO()
        call_command("export_breaks", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_breaks_csv(self.salon, DAY, DAY))

    def test_breaks_filtered_cli_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_breaks", "--salon-id", str(self.salon.pk),
            "--date-from", DAY.isoformat(), "--date-to", DAY.isoformat(),
            "--staff-member", str(self.staff.pk), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_breaks_csv(self.salon, DAY, DAY,
                              staff_member=self.staff.pk))
        self.assertIn("Stylist One", out.getvalue())
        self.assertNotIn("Stylist Two", out.getvalue())
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_breaks_filtered_kwargs_instance_matches_service(self):
        out = io.StringIO()
        call_command("export_breaks", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, staff_member=self.staff2,
                     stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_breaks_csv(self.salon, DAY, DAY,
                              staff_member=self.staff2))

    def test_breaks_other_salon_staff_exports_header_only(self):
        out = io.StringIO()
        call_command("export_breaks", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY,
                     staff_member=self.other_staff.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_breaks_csv(self.salon, DAY, DAY,
                              staff_member=self.other_staff.pk))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)

    # -- export_break_totals -------------------------------------------
    def test_break_totals_unfiltered_matches_service(self):
        out = io.StringIO()
        call_command("export_break_totals", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_break_totals_csv(self.salon, DAY, DAY))

    def test_break_totals_filtered_cli_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_break_totals", "--salon-id", str(self.salon.pk),
            "--date-from", DAY.isoformat(), "--date-to", DAY.isoformat(),
            "--staff-member", str(self.staff2.pk), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_break_totals_csv(self.salon, DAY, DAY,
                                    staff_member=self.staff2.pk))
        self.assertIn("Stylist Two", out.getvalue())
        self.assertNotIn("Stylist One", out.getvalue())
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_break_totals_filtered_kwargs_instance(self):
        out = io.StringIO()
        call_command("export_break_totals", salon_id=self.salon.pk,
                     date_from=DAY, date_to=DAY, staff_member=self.staff,
                     stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_break_totals_csv(self.salon, DAY, DAY,
                                    staff_member=self.staff))

    # -- export_prior_break_totals --------------------------------------
    def test_prior_unfiltered_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_break_totals", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_break_totals_csv(self.salon, DAY, DAY))

    def test_prior_filtered_cli_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_prior_break_totals", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--staff-member", str(self.staff.pk), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_break_totals_csv(self.salon, DAY, DAY,
                                          staff_member=self.staff.pk))
        self.assertIn("Stylist One", out.getvalue())
        self.assertNotIn("Stylist Two", out.getvalue())
        # Total row + the one scoped staff row.
        self.assertEqual(len(out.getvalue().strip().splitlines()), 3)

    def test_prior_filtered_kwargs_instance(self):
        out = io.StringIO()
        call_command("export_prior_break_totals", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY,
                     staff_member=self.staff2, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_break_totals_csv(self.salon, DAY, DAY,
                                          staff_member=self.staff2))
        self.assertNotIn("Stylist One", out.getvalue())
