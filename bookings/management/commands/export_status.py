"""Export one salon's appointment status counts as CSV.

Usage:
    python manage.py export_status --salon-id ID --date YYYY-MM-DD
        [--end-day YYYY-MM-DD] [--date-from YYYY-MM-DD]
        [--date-to YYYY-MM-DD] [--output PATH]

Thin wrapper around the existing
:func:`bookings.status_export.export_status_counts_csv` service:
the salon is resolved by id, dates are parsed to
``datetime.date`` objects, and every filter is passed to the
service verbatim -- its CSV text is written unchanged, to
``--output`` when given and to stdout otherwise. This command
adds no export logic of its own, so command and service output
can never disagree -- one source of truth. Backend only;
read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings.status_export import export_status_counts_csv
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
    help = "Export one salon's appointment status counts as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose status counts to export.",
        )
        parser.add_argument(
            "--date", "--day", dest="date", type=_parse_date,
            default=None,
            help="Day to count, YYYY-MM-DD.",
        )
        parser.add_argument(
            "--end-day", dest="end_day", type=_parse_date, default=None,
            help="Last day of an inclusive range, YYYY-MM-DD.",
        )
        parser.add_argument(
            "--date-from", "--from-date", "--start-date",
            dest="date_from", type=_parse_date, default=None,
            help="Inclusive first day of a range, YYYY-MM-DD.",
        )
        parser.add_argument(
            "--date-to", "--to-date", "--end-date",
            dest="date_to", type=_parse_date, default=None,
            help="Inclusive last day of a range, YYYY-MM-DD.",
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
        end_day = _coerce_date(options.get("end_day"), "end_day")
        date_from = _coerce_date(options.get("date_from"), "date_from")
        date_to = _coerce_date(options.get("date_to"), "date_to")
        # ``start_date``/``end_date`` are service aliases for
        # ``date_from``/``date_to`` if supplied via call_command.
        start_date = _coerce_date(
            options.get("start_date"), "start_date")
        end_date = _coerce_date(options.get("end_date"), "end_date")
        try:
            text = export_status_counts_csv(
                salon, day, end_day,
                date_from=date_from, date_to=date_to,
                start_date=start_date, end_date=end_date,
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
