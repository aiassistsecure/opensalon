"""Export one salon's appointments for a date range as JSON.

Usage:
    python manage.py export_appointments --salon-id ID
        --date-from YYYY-MM-DD [--date-to YYYY-MM-DD]
        [--no-include-cancelled] [--output PATH]

Thin wrapper around the existing
:func:`bookings.export.export_appointments` service: the salon
is resolved by id, the dates are parsed to ``datetime.date``
objects, and both are passed to the service verbatim (with its
``include_cancelled`` flag) -- its JSON-serializable list is
serialized as JSON, to ``--output`` when given and to stdout
otherwise. The service has no CSV variant; JSON serialization
of its result, as in the ``export_clients`` and
``export_movement`` commands, is the only rendering here. This
command adds no export logic of its own, so command and
service output can never disagree -- one source of truth.
Backend only; read-only.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from bookings.export import export_appointments
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


class Command(BaseCommand):
    help = "Export one salon's appointments for a date range as JSON."

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
            "--output", default=None,
            help="Path to write the JSON to (default: stdout).",
        )

    def handle(self, *args, **options):
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
        try:
            rows = export_appointments(
                salon, date_from, date_to,
                include_cancelled=include_cancelled,
            )
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
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
