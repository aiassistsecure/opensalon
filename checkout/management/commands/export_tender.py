"""Export a salon's tender totals as CSV.

Usage:
    python manage.py export_tender --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD
        [--output PATH]

Thin wrapper around the existing
:func:`checkout.tender_export.export_tender_totals_csv`
service: the salon is resolved by id, the dates are parsed to
``datetime.date`` objects, and both are passed to the service
verbatim -- its CSV text is written unchanged, to ``--output``
when given and to stdout otherwise. The service needs both
range ends, so ``--start-date`` and ``--end-date`` are both
required here too. This command adds no export logic of its
own, so command and service output can never disagree -- one
source of truth.

Invalid input -- an unparseable date or a reversed range --
raises ``CommandError``, as do service errors. Dates mean
whole days, inclusive at both ends, exactly as the service
defines them. Read-only. Core stays provider-agnostic -- no
payment-provider SDK, field, or name appears here.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from checkout.tender_export import export_tender_totals_csv
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
    help = "Export a salon's tender totals as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose tender totals to export.",
        )
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            required=True,
            help="First day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            required=True,
            help="Last day of the range, YYYY-MM-DD (inclusive).",
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
        start = _parse_date(options["start_date"], "start date")
        end = _parse_date(options["end_date"], "end date")
        if end is not None and start is not None and end < start:
            raise CommandError(
                f"End date {end.isoformat()} is before start date "
                f"{start.isoformat()}."
            )
        try:
            text = export_tender_totals_csv(start, end, salon=salon)
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
