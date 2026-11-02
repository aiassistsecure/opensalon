"""Export a salon's stock movement summary as CSV.

Usage:
    python manage.py export_movement_summary --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD
        [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around
:func:`catalog.movement_summary_export.export_movement_summary_csv`:
it resolves the salon by id, parses the dates, delegates to that
service verbatim (with the same ``start`` / ``end`` / ``salon``),
and writes the returned CSV to ``--output`` when given, otherwise
to stdout. It adds no fields, filtering, or formatting of its
own, so the command output and the service output can never
disagree — one source of truth.

Range semantics are the service's own: both bounds are required,
inclusive, and cover whole local days; a reversed range raises
the service's ``ValueError``, surfaced here as ``CommandError``,
as does an unknown salon or an unparseable date.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from catalog.movement_summary_export import export_movement_summary_csv
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
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's stock movement summary as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose movement summary to export.",
        )
        parser.add_argument(
            "--start-date", "--start", dest="start_date",
            default=None,
            help="First day of the range, YYYY-MM-DD (inclusive; "
                 "required by the service).",
        )
        parser.add_argument(
            "--end-date", "--end", dest="end_date",
            default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive; "
                 "required by the service).",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        start = _parse_date(options["start_date"])
        end = _parse_date(options["end_date"])
        try:
            text = export_movement_summary_csv(start, end, salon=salon)
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
