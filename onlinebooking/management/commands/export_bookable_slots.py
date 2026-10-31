"""Export one salon's bookable slots for one service on one day as CSV.

Usage:
    python manage.py export_bookable_slots --salon-id ID
        --service-id ID --date YYYY-MM-DD [--output PATH]

Thin wrapper around the existing
:func:`onlinebooking.bookable_slots_export.export_bookable_slots_csv`
service: this command delegates verbatim to
``export_bookable_slots_csv(salon, service, day)``
and adds no export logic of its own, so the command output and
the service output can never disagree -- one source of truth.

The salon is resolved by ``--salon-id`` and the service by
``--service-id``; an unknown id for either raises
``CommandError``. The ``--date`` day is passed through to the
service unchanged (a ``datetime.date`` from the CLI parser, or
the object a programmatic caller supplied).

Output goes to stdout unless ``--output`` names a file.
Invalid input -- an unknown salon, an unknown service, or an
unparseable ``--date`` -- raises ``CommandError``, as do
service errors and unwritable output.
Backend only -- no views, templates, or UI. Read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from onlinebooking.bookable_slots_export import export_bookable_slots_csv
from saloncore.models import Salon, Service


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _coerce_date(value):
    if value is None or isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise CommandError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one salon's bookable slots for a service as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose bookable slots to export.")
        parser.add_argument(
            "--service-id", dest="service_id", required=True, type=int,
            help="Id of the service to export bookable slots for.")
        parser.add_argument(
            "--date", dest="date", type=_parse_date, required=True,
            help="Day to export, YYYY-MM-DD.")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        try:
            service = Service.objects.get(pk=options["service_id"])
        except Service.DoesNotExist:
            raise CommandError(
                f"No service with id {options['service_id']}.") from None

        day = _coerce_date(options.get("date"))
        if day is None:
            raise CommandError("A --date is required.")

        try:
            text = export_bookable_slots_csv(salon, service, day)
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
