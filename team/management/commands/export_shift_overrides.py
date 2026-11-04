"""Export one salon's shift overrides as CSV.

Usage:
    python manage.py export_shift_overrides --salon-id ID
        [--staff-member-id ID]
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--output PATH]

Thin wrapper around the existing
:func:`team.shift_override_export.export_shift_overrides_csv`
service: the salon is resolved by id and passed to the service
verbatim -- its CSV text is written unchanged, to ``--output``
when given and to stdout otherwise. This command adds no
export logic of its own, so command and service output can
never disagree -- one source of truth.

With ``--staff-member-id`` the export is narrowed to that one
staff member's shift overrides: the staff member is resolved
by id within the salon (a staff member from another salon, or
an unknown id, is a ``CommandError``), and the resolved staff
member is passed to the service as its optional
``staff_member`` argument. Without ``--staff-member-id`` the
command exports the whole salon, exactly as before.

With ``--start-date`` / ``--end-date`` (spelled as the other
Family XI ledger commands spell them; ``--date-from`` /
``--date-to`` accepted as aliases) the export is narrowed to
overrides whose own ``date`` falls in that inclusive window:
the dates are parsed to ``datetime.date`` objects and passed
to the service as its optional ``start_date`` / ``end_date``
arguments. Each bound is optional; without either, the
command exports every override, exactly as before. A reversed
window exports the header alone. The window composes with
``--staff-member-id`` (window AND member).

An unknown salon raises ``CommandError``. Backend only -- no
views, templates, or UI. Read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.models import StaffMember
from team.shift_override_export import export_shift_overrides_csv


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _coerce_date(value, label):
    if value is None or isinstance(value, datetime.date):
        # Dates pass verbatim; datetimes pass too -- the service
        # reduces them to their salon-local date.
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one salon's shift overrides as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose shift overrides to export.")
        parser.add_argument(
            "--staff-member-id", type=int, default=None,
            help="ID of the staff member (in the salon) whose "
                 "shift overrides to export "
                 "(default: all staff members).")
        parser.add_argument(
            "--start-date", "--date-from", "--from-date",
            dest="start_date", type=_parse_date, default=None,
            help="Inclusive first day of the window on the "
                 "override date, YYYY-MM-DD "
                 "(default: unbounded).")
        parser.add_argument(
            "--end-date", "--date-to", "--to-date",
            dest="end_date", type=_parse_date, default=None,
            help="Inclusive last day of the window on the "
                 "override date, YYYY-MM-DD "
                 "(default: unbounded).")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        staff_member = None
        if options.get("staff_member_id") is not None:
            try:
                staff_member = StaffMember.objects.get(
                    pk=options["staff_member_id"], salon=salon
                )
            except StaffMember.DoesNotExist:
                raise CommandError(
                    f"No staff member with id "
                    f"{options['staff_member_id']} "
                    f"for salon {options['salon_id']}.") from None

        start_date = _coerce_date(
            options.get("start_date"), "start-date")
        end_date = _coerce_date(options.get("end_date"), "end-date")
        try:
            text = export_shift_overrides_csv(
                salon, staff_member=staff_member,
                start_date=start_date, end_date=end_date)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: "
                    f"{exc}") from exc
        else:
            self.stdout.write(text, ending="")
