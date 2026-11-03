"""Export one salon's Break rows verbatim as CSV.

Usage:
    python manage.py export_breaks --salon-id ID
        [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD]
        [--staff-member ID] [--output PATH]

Thin wrapper around
:func:`bookings.breaks_export.export_breaks_csv`: the salon is
resolved by id, the dates are parsed to ``datetime.date``
objects, and both are passed to the service verbatim -- its
CSV text is written unchanged, to ``--output`` when given and
to stdout otherwise. With no dates, every break for the salon
is exported. This command adds no export logic of its own, so
command and service output can never disagree -- one source
of truth. An unknown salon raises ``CommandError``.
Backend only; read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings.breaks_export import export_breaks_csv
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _coerce_date(value, label):
    if value is None or isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc



def _coerce_staff(value):
    if value is None:
        return None
    # StaffMember instance passes through verbatim.
    pk = getattr(value, "pk", value)
    if isinstance(pk, int):
        return pk
    try:
        return int(pk)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"Invalid staff member {value!r}; expected an id."
        ) from exc

class Command(BaseCommand):
    help = "Export one salon's Break rows verbatim as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose breaks to export.",
        )
        parser.add_argument(
            "--date-from", "--from-date", "--start-date",
            dest="date_from", type=_parse_date, default=None,
            help="Inclusive first day of a range, YYYY-MM-DD.",
        )
        parser.add_argument(
            "--date-to", "--to-date", "--end-date",
            dest="date_to", type=_parse_date, default=None,
            help="Inclusive last day of a range, YYYY-MM-DD "
                 "(default: the service's own default).",
        )
        parser.add_argument(
            "--staff-member", "--staff-member-id", "--staff-id",
            dest="staff_member", type=int, default=None,
            help="Id of the staff member to scope to.",
        )
        parser.add_argument(
            "--staff", dest="staff_member_id",
            type=int, default=None,
            help="Alias for --staff-member (id of the staff member).",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the CSV to (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        date_from = _coerce_date(options.get("date_from"), "date_from")
        date_to = _coerce_date(options.get("date_to"), "date_to")
        staff_raw = options.get("staff_member")
        if staff_raw is None:
            staff_raw = options.get("staff_member_id")
        staff_member = _coerce_staff(staff_raw)
        try:
            text = export_breaks_csv(
                salon, date_from, date_to, staff_member=staff_member)
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
