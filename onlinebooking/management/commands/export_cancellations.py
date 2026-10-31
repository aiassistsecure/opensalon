"""Export one salon's online cancellations summary as CSV.

Usage:
    python manage.py export_cancellations --salon-id ID
        [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD]
        [--output PATH]

Thin wrapper around the existing
:func:`onlinebooking.cancellations_export.export_cancellations_csv`
service: this command delegates verbatim to
``export_cancellations_csv(salon, date_from=None, date_to=None)``
and adds no export logic of its own, so the command output and
the service output can never disagree -- one source of truth.

Both dates are optional and default to ``None`` exactly as the
service defines them (no range: every matching cancellation).
``--start-date`` / ``--end-date`` are accepted as aliases for
``--date-from`` / ``--date-to``.

Output goes to stdout unless ``--output`` names a file.
Invalid input -- an unknown salon, an unparseable date, or a
reversed range -- raises ``CommandError``. Dates mean whole
local days in the salon's timezone, inclusive at both ends,
exactly as the service defines them.
Backend only -- no views, templates, or UI. Read-only.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from onlinebooking.cancellations_export import export_cancellations_csv
from saloncore.models import Salon


def _parse_date(value, label):
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
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one salon's online cancellations summary as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose cancellations to export.")
        parser.add_argument(
            "--date-from", "--start-date", dest="date_from",
            default=None,
            help="First day of the range, YYYY-MM-DD (inclusive; "
                 "default: no range, as the service defines it).")
        parser.add_argument(
            "--date-to", "--end-date", dest="date_to",
            default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive; "
                 "default: no range, as the service defines it).")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        date_from = _parse_date(options["date_from"], "date-from")
        date_to = _parse_date(options["date_to"], "date-to")
        if (date_from is not None and date_to is not None
                and date_to < date_from):
            raise CommandError(
                f"End date {date_to.isoformat()} is before start date "
                f"{date_from.isoformat()}.")

        try:
            text = export_cancellations_csv(salon, date_from, date_to)
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
