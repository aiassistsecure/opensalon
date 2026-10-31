"""Export one salon's per-staff day load for one day as CSV.

Usage:
    python manage.py export_staff_day --salon-id ID
        --date YYYY-MM-DD [--output PATH]

Thin wrapper around the existing
:func:`bookings.staff_day_export.export_staff_day_csv`
service: the salon is resolved by id, the date is parsed to a
``datetime.date``, and both are passed to the service verbatim
-- its CSV text is written unchanged, to ``--output`` when
given and to stdout otherwise. This command adds no export
logic of its own, so command and service output can never
disagree -- one source of truth. Backend only; read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings.staff_day_export import export_staff_day_csv
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


class Command(BaseCommand):
    help = "Export one salon's per-staff day load for one day as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose staff day to export.",
        )
        parser.add_argument(
            "--date", "--day", dest="date", type=_parse_date,
            default=None,
            help="Day to export, YYYY-MM-DD.",
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
        try:
            text = export_staff_day_csv(salon, day)
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
