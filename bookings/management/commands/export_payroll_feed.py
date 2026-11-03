"""Export one salon's combined per-staff payroll feed as CSV.

Usage: export_payroll_feed --salon-id ID --start-date YYYY-MM-DD
--end-date YYYY-MM-DD [--staff-member ID] [--output PATH].
Thin wrapper around
:func:`bookings.payroll_feed_export.export_payroll_feed_csv`:
the staff id is resolved to its ``StaffMember`` (the service
scopes on the instance) and passed through; an unknown or
invalid staff id raises ``CommandError``. Omitted, the export
is the previous salon-wide feed verbatim.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings.payroll_feed_export import export_payroll_feed_csv
from saloncore.models import Salon
from team.models import StaffMember


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD.") from exc


def _coerce_date(value, label):
    if value is None or isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD.") from exc


def _resolve_staff(value):
    if value is None or isinstance(value, StaffMember):
        return value
    pk = getattr(value, "pk", value)
    try:
        pk = int(pk)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"Invalid staff member {value!r}; expected an id.") from exc
    try:
        return StaffMember.objects.get(pk=pk)
    except StaffMember.DoesNotExist as exc:
        raise CommandError(f"No staff member with id {pk}.") from exc


class Command(BaseCommand):
    help = "Export one salon's combined per-staff payroll feed as CSV."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon whose feed to export.")
        parser.add_argument(
            "--start-date", "--date-from", "--from-date", dest="start_date",
            type=_parse_date, default=None,
            help="Inclusive first day, YYYY-MM-DD.")
        parser.add_argument(
            "--end-date", "--date-to", "--to-date", dest="end_date",
            type=_parse_date, default=None,
            help="Inclusive last day, YYYY-MM-DD.")
        parser.add_argument(
            "--staff-member", "--staff-member-id", "--staff-id",
            dest="staff_member", type=int, default=None,
            help="Id of the staff member to scope to.")
        parser.add_argument("--staff", dest="staff_member_id",
                            type=int, default=None,
                            help="Alias for --staff-member (id).")
        parser.add_argument("--output", default=None,
                            help="Path to write the CSV to (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        start = _coerce_date(options.get("start_date"), "start_date")
        end = _coerce_date(options.get("end_date"), "end_date")
        if start is None:
            raise CommandError("A --start-date is required.")
        if end is None:
            raise CommandError("A --end-date is required.")
        if end < start:
            raise CommandError("--end-date must not be before --start-date.")
        staff_raw = options.get("staff_member")
        if staff_raw is None:
            staff_raw = options.get("staff_member_id")
        staff_member = _resolve_staff(staff_raw)
        try:
            text = export_payroll_feed_csv(
                salon, start, end, staff_member=staff_member)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if options.get("output"):
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
