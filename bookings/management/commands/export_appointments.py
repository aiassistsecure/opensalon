"""Export one salon's appointments for a date range as JSON or CSV.

Usage:
    python manage.py export_appointments --salon-id ID
        --date-from YYYY-MM-DD [--date-to YYYY-MM-DD]
        [--no-include-cancelled] [--staff-member-id ID]
        [--format json|csv] [--output PATH]

Thin wrapper around the existing
:func:`bookings.export.export_appointments` service: the salon
is resolved by id, the dates are parsed to ``datetime.date``
objects, and both are passed to the service verbatim (with its
``include_cancelled`` flag) -- its JSON-serializable list is
rendered as JSON for ``--format json`` (the default, exactly as
before), or as CSV for ``--format csv`` (the same rows written
with :data:`bookings.export.EXPORT_FIELDNAMES` as the header,
in that order; a nested dict/list value is JSON-encoded into
its cell so nothing is dropped). The optional
``--staff-member-id`` is resolved to its ``StaffMember`` in
the salon and passed to the service as its ``staff_member``
filter; an id that is unknown — or belongs to another salon —
raises ``CommandError``. Omitted, the export is the previous
salon-wide output verbatim. Output goes to ``--output``
when given and to stdout otherwise. This command adds no
export logic of its own -- no new querying, filtering, or
field changes -- so command and service output can never
disagree -- one source of truth. Backend only; read-only.
"""
import argparse
import csv
import datetime
import io
import json

from django.core.management.base import BaseCommand, CommandError

from bookings.export import EXPORT_FIELDNAMES, export_appointments
from saloncore.models import Salon
from team.models import StaffMember

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
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


def _resolve_staff_member(value, salon):
    if value is None:
        return None
    # A StaffMember instance (via call_command kwargs) resolves by pk.
    pk = getattr(value, "pk", value)
    try:
        pk = int(pk)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"Invalid staff member {value!r}; expected an id."
        ) from exc
    try:
        return StaffMember.objects.get(pk=pk, salon=salon)
    except (StaffMember.DoesNotExist, TypeError, ValueError) as exc:
        raise CommandError(
            f"No staff member with id {pk}."
        ) from exc


def _coerce_include_cancelled(value):
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
        raise CommandError(
            f"Invalid include_cancelled {value!r}; expected a boolean."
        )
    return bool(value)


def _csv_cell(value):
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, sort_keys=isinstance(value, dict))
    return value


def _rows_to_csv(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_cell(row.get(key))
                         for key in EXPORT_FIELDNAMES})
    return buffer.getvalue()


class Command(BaseCommand):
    help = "Export one salon's appointments for a date range as JSON or CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose appointments to export.",
        )
        parser.add_argument(
            "--date-from", dest="date_from", type=_parse_date,
            required=True,
            help="First day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--date-to", dest="date_to", type=_parse_date, default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive; "
                 "default: the --date-from day).",
        )
        parser.add_argument(
            "--include-cancelled", dest="include_cancelled",
            action=argparse.BooleanOptionalAction, default=True,
            help="Include cancelled appointments (default: included; "
                 "use --no-include-cancelled to exclude them).",
        )
        parser.add_argument(
            "--staff-member-id", dest="staff_member_id",
            type=int, default=None,
            help="Id of the staff member to scope to (default: "
                 "every staff member in the salon).",
        )
        parser.add_argument(
            "--format", dest="format", default="json", choices=_FORMATS,
            help="Export format: json (default) or csv.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the export to (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "json"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except (Salon.DoesNotExist, TypeError, ValueError) as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        date_from = _coerce_date(options.get("date_from"), "date-from")
        if date_from is None:
            raise CommandError("A --date-from is required.")
        date_to = _coerce_date(options.get("date_to"), "date-to")
        include_cancelled = _coerce_include_cancelled(
            options.get("include_cancelled", True))
        staff_raw = options.get("staff_member_id")
        if staff_raw is None:
            staff_raw = options.get("staff_member")
        staff_member = _resolve_staff_member(staff_raw, salon)
        try:
            rows = export_appointments(
                salon, date_from, date_to,
                include_cancelled=include_cancelled,
                staff_member=staff_member,
            )
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if fmt == "csv":
            text = _rows_to_csv(rows)
        else:
            text = json.dumps(rows, indent=2) + "\n"
        if options.get("output"):
            try:
                with open(options["output"], "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
