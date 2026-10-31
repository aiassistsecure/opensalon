"""Export a salon's last-7-days revenue split as CSV.

Usage:
    python manage.py export_split --salon-id ID
        [--today YYYY-MM-DD] [--output PATH]

Thin wrapper around the existing
:func:`insights.split_export.export_split_csv` service: the
salon is resolved by id, ``--today`` is passed to the service
verbatim — its CSV text is written unchanged, to ``--output``
when given and to stdout otherwise. ``--today`` defaults to
``None``, exactly as the service defines it. This command
adds no export logic of its own, so command and service output
can never disagree — one source of truth.

An unknown salon or an unparseable date raises
``CommandError``. Dates mean whole local days in the salon's
timezone, inclusive, exactly as the service defines them.
Read-only.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from insights.split_export import export_split_csv
from saloncore.models import Salon


def _parse_date(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid today {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's last-7-days revenue split as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose revenue split to export.",
        )
        parser.add_argument(
            "--today", "--end-date", "--end", "--date-to", dest="today",
            default=None,
            help="Last day of the 7-day window, YYYY-MM-DD "
                 "(inclusive; default: the service's own default).",
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
        today = _parse_date(options["today"])
        try:
            text = export_split_csv(salon, today=today)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if options["output"]:
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
