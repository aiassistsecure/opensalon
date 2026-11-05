"""Export one salon's shift overrides as CSV or JSON.

Usage:
    python manage.py export_shift_overrides --salon-id ID
        [--staff-member-id ID]
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--is-off-only | --is-on-only]
        [--format json|csv]
        [--output PATH]

Thin wrapper around the existing
:mod:`team.shift_override_export` service: the salon is
resolved by id and passed to the service verbatim. For
``--format csv`` (the default) it delegates verbatim to
:func:`team.shift_override_export.export_shift_overrides_csv`,
so CSV output is byte-identical to before; for
``--format json`` it serialises the SAME dict rows from
:func:`team.shift_override_export.export_shift_overrides` as
JSON via ``DjangoJSONEncoder``, so the two formats can never
disagree -- one source of truth. The text is written to
``--output`` when given and to stdout otherwise. An unknown
``--format`` raises ``CommandError`` (argparse ``choices``
reject it on the CLI; the explicit check covers
``call_command`` kwargs).

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

With ``--is-off-only`` only full-day-off overrides (stored
``is_off`` true) are exported; with ``--is-on-only`` only
placed-shift overrides (stored ``is_off`` false). The flags
conflict if both are given (``CommandError``). Without
either, the selection is unfiltered, exactly as before. They
compose with ``--staff-member-id`` and the date window.

An unknown salon raises ``CommandError``. Backend only -- no
views, templates, or UI. Read-only.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from saloncore.models import Salon
from team.models import StaffMember
from team.shift_override_export import (
    export_shift_overrides,
    export_shift_overrides_csv,
)

_FORMATS = ("json", "csv")


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
    help = "Export one salon's shift overrides as CSV (default) or JSON."

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
            "--is-off-only", action="store_true",
            help="Only full-day-off overrides (is_off).")
        parser.add_argument(
            "--is-on-only", action="store_true",
            help="Only placed-shift overrides (not is_off).")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        if options.get("is_off_only") and options.get("is_on_only"):
            raise CommandError(
                "--is-off-only and --is-on-only conflict.")
        is_off = (
            True if options.get("is_off_only")
            else False if options.get("is_on_only") else None)
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
            if fmt == "json":
                rows = export_shift_overrides(
                    salon, staff_member=staff_member,
                    start_date=start_date, end_date=end_date,
                    is_off=is_off)
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_shift_overrides_csv(
                    salon, staff_member=staff_member,
                    start_date=start_date, end_date=end_date,
                    is_off=is_off)
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
