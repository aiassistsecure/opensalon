"""Export one salon's available slots for one day as CSV.

Usage:
    python manage.py export_available_slots --salon-id ID
        --date YYYY-MM-DD [--service-id ID] [--online-only]
        [--output PATH]

Thin wrapper around the existing
:func:`bookings.availability_export.export_available_slots_csv`
service: the salon (and optional service) are resolved by id,
the date is parsed to a ``datetime.date``, and every filter is
passed to the service verbatim -- its CSV text is written
unchanged, to ``--output`` when given and to stdout otherwise.
This command adds no export logic of its own, so command and
service output can never disagree -- one source of truth.
Backend only; read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings.availability_export import export_available_slots_csv
from saloncore.models import Salon, Service


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


class Command(BaseCommand):
    help = "Export one salon's available slots for one day as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose available slots to export.",
        )
        parser.add_argument(
            "--date", "--day", dest="date", type=_parse_date,
            default=None,
            help="Day to export, YYYY-MM-DD.",
        )
        parser.add_argument(
            "--service-id", dest="service_id", type=int, default=None,
            help="Id of a service to filter slots by its length.",
        )
        parser.add_argument(
            "--online-only", dest="online_only",
            action="store_true", default=False,
            help="Only include online-bookable staff.",
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
        day = _coerce_date(options.get("date"), "date")
        if day is None:
            raise CommandError("A --date is required.")
        # ``service`` may be supplied via call_command as a
        # Service instance or an id; ``--service-id`` is the CLI form.
        service = options.get("service")
        service_id = options.get("service_id")
        if service is not None and service_id is None:
            if isinstance(service, Service):
                service_id = None
            elif isinstance(service, int):
                service_id = service
                service = None
            else:
                raise CommandError(
                    f"Invalid service {service!r}; expected a service id."
                )
        if service_id is not None:
            try:
                service = Service.objects.get(pk=service_id)
            except Service.DoesNotExist as exc:
                raise CommandError(
                    f"No service with id {service_id}."
                ) from exc
        online_only = bool(options.get("online_only", False))
        try:
            text = export_available_slots_csv(
                salon, day, service=service, online_only=online_only,
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
