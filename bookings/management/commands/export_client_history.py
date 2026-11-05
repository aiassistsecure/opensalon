"""Export one client's appointment history as CSV.

Usage:
    python manage.py export_client_history --salon-id ID
        --client-id ID [--upcoming-only]
        [--now ISO-8601-DATETIME]
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--status STATUS]
        [--output PATH]

Thin wrapper around the existing
:func:`bookings.client_history_export.export_client_history_csv`
service: the salon and client are resolved by id, and both are
passed to the service verbatim as
``export_client_history_csv(salon, client,
upcoming_only=..., now=..., start_date=..., end_date=...,
status=...)`` --
its CSV text is written unchanged, to ``--output`` when given
and to stdout otherwise. ``--status`` is the optional exact
stored appointment status to filter by, spelled as the other
history commands spell it; omitted, no status filter applies.
``--start-date`` / ``--end-date`` are
the optional inclusive local-date window on appointment
``start``, spelled as the other bookings ledger commands spell
them (``--date-from`` / ``--date-to`` accepted as aliases);
omitted, the export is the previous unbounded output verbatim.
A client from another salon is passed through too: the service
exports it as a header-only CSV, exactly as it does directly.
This command adds no export logic of its own, so command and
service output can never disagree -- one source of truth.
Backend only; read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings.client_history_export import export_client_history_csv
from clients.models import Client
from saloncore.models import Salon


def _parse_datetime(value):
    try:
        return _datetime_from_string(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid datetime {value!r}; expected ISO-8601."
        ) from exc


def _datetime_from_string(value):
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(text)


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


def _coerce_now(value):
    if value is None or isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(
            value, datetime.time.min, tzinfo=datetime.timezone.utc)
    try:
        return _datetime_from_string(value)
    except ValueError as exc:
        raise CommandError(
            f"Invalid now {value!r}; expected ISO-8601 datetime."
        ) from exc


def _resolve(model, value, label):
    if value is None or isinstance(value, model):
        return value
    pk = getattr(value, "pk", value)
    try:
        pk = int(pk)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected an id."
        ) from exc
    try:
        return model.objects.get(pk=pk)
    except model.DoesNotExist as exc:
        raise CommandError(f"No {label} with id {pk}.") from exc


class Command(BaseCommand):
    help = "Export one client's appointment history as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose client history to export.",
        )
        parser.add_argument(
            "--client-id", "--client", dest="client_id",
            type=int, required=True,
            help="Id of the client whose history to export.",
        )
        parser.add_argument(
            "--upcoming-only", "--upcoming", dest="upcoming_only",
            action="store_true", default=False,
            help="Export only upcoming appointments (soonest first).",
        )
        parser.add_argument(
            "--now", dest="now", type=_parse_datetime, default=None,
            help="Reference instant for --upcoming-only, ISO-8601 "
                 "(default: the service's own default).",
        )
        parser.add_argument(
            "--start-date", "--date-from", "--from-date",
            dest="start_date", type=_parse_date, default=None,
            help="Inclusive first day of the window on appointment "
                 "start, YYYY-MM-DD (default: unbounded).",
        )
        parser.add_argument(
            "--end-date", "--date-to", "--to-date",
            dest="end_date", type=_parse_date, default=None,
            help="Inclusive last day of the window on appointment "
                 "start, YYYY-MM-DD (default: unbounded).",
        )
        parser.add_argument(
            "--status", dest="status", default=None,
            help="Appointment status value to filter by (default: "
                 "no status filter, as the service defines it).",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the CSV to (default: stdout).",
        )

    def handle(self, *args, **options):
        salon = _resolve(Salon, options.get("salon_id"), "salon")
        if salon is None:
            raise CommandError("A --salon-id is required.")
        client = _resolve(Client, options.get("client_id"), "client")
        if client is None:
            raise CommandError("A --client-id is required.")
        now = _coerce_now(options.get("now"))
        start_date = _coerce_date(options.get("start_date"), "start-date")
        end_date = _coerce_date(options.get("end_date"), "end-date")
        try:
            text = export_client_history_csv(
                salon, client,
                upcoming_only=bool(options.get("upcoming_only")),
                now=now,
                start_date=start_date,
                end_date=end_date,
                status=options.get("status"),
            )
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
