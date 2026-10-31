"""Export one client's appointment history as CSV.

Usage:
    python manage.py export_client_history --salon-id ID
        --client-id ID [--upcoming-only]
        [--now ISO-8601-DATETIME] [--output PATH]

Thin wrapper around the existing
:func:`bookings.client_history_export.export_client_history_csv`
service: the salon and client are resolved by id, and both are
passed to the service verbatim as
``export_client_history_csv(salon, client,
upcoming_only=..., now=...)`` -- its CSV text is written
unchanged, to ``--output`` when given and to stdout otherwise.
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
        try:
            text = export_client_history_csv(
                salon, client,
                upcoming_only=bool(options.get("upcoming_only")),
                now=now,
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
