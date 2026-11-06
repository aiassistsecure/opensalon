"""Export one salon's appointment search results as CSV or JSON.

Usage:
    python manage.py export_appointment_search --salon-id ID
        [--query TEXT] [--date-from YYYY-MM-DD]
        [--date-to YYYY-MM-DD] [--staff-member ID]
        [--status STATUS] [--format json|csv] [--output PATH]

Thin wrapper around :mod:`bookings.search_export`: the salon
is resolved by id, the optional dates are parsed to
``datetime.date`` objects, and every filter is passed to the
service verbatim. For ``--format csv`` (the default) it writes
:func:`bookings.search_export.export_search_csv`'s CSV string
as-is, so the historical CSV output is byte-identical; for
``--format json`` it serialises the same dict rows from
:func:`bookings.search_export.export_search_appointments` --
the same rows the CSV is built from -- as JSON via
``DjangoJSONEncoder``. Output is written unchanged to
``--output`` or stdout. No export logic of its own (one source
of truth). Unknown salon, unparseable date, service error, or
unknown format raises ``CommandError``. Backend only; read-only.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from bookings.search_export import (
    export_search_appointments,
    export_search_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _coerce_date(value, label):
    if value is None or isinstance(
            value, (datetime.date, datetime.datetime)):
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
    help = "Export one salon's appointment search results as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose appointments to search.",
        )
        parser.add_argument(
            "--query", "--search", dest="query", default=None,
            help="Client-name substring to match (case-insensitive).",
        )
        parser.add_argument(
            "--date-from", "--from-date", "--start-date",
            dest="date_from", type=_parse_date, default=None,
            help="Inclusive lower bound on start, YYYY-MM-DD.",
        )
        parser.add_argument(
            "--date-to", "--to-date", "--end-date",
            dest="date_to", type=_parse_date, default=None,
            help="Inclusive upper bound on start, YYYY-MM-DD "
                 "(the whole day is included).",
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
            "--status", dest="status", default=None,
            help="Appointment status value to scope to.",
        )
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the export to (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'."
            )
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
        filters = dict(
            query=options.get("query"),
            date_from=date_from,
            date_to=date_to,
            staff_member=staff_member,
            status=options.get("status"),
        )
        try:
            if fmt == "json":
                text = json.dumps(
                    export_search_appointments(salon, **filters),
                    indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_search_csv(salon, **filters)
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
