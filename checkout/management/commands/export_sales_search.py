"""Export a salon's sale search results as CSV.

Usage:
    python manage.py export_sales_search --salon-id ID
        [--client-name TEXT] [--date-from YYYY-MM-DD]
        [--date-to YYYY-MM-DD] [--min-total AMOUNT]
        [--include-voided] [--output PATH]

Thin wrapper around the existing
:func:`checkout.search_export.export_search_sales_csv` service:
the salon is resolved by id, the dates are parsed to
``datetime.date`` objects, and every filter is passed to the
service verbatim -- its CSV text is written unchanged, to
``--output`` when given and to stdout otherwise. All filters
are optional exactly as the service defines them, so omitting
them exports every (non-voided) sale for the salon. This
command adds no export logic of its own, so command and
service output can never disagree -- one source of truth.

Invalid input -- an unparseable date or a reversed range --
raises ``CommandError``, as do service errors. Dates mean
whole local days in the salon's timezone, inclusive at both
ends, exactly as the service defines them. Read-only. Core
stays provider-agnostic -- no payment-provider SDK, field,
or name appears here.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from checkout.search_export import export_search_sales_csv
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
    help = "Export a salon's sale search results as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose sales to export.",
        )
        parser.add_argument(
            "--client-name", "--name",
            dest="client_name", default=None,
            help="Client name fragment to match (case-insensitive; "
                 "default: no name filter).",
        )
        parser.add_argument(
            "--date-from", "--start-date", "--start", dest="date_from",
            default=None,
            help="First day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
        )
        parser.add_argument(
            "--date-to", "--end-date", "--end", dest="date_to",
            default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
        )
        parser.add_argument(
            "--min-total", dest="min_total", default=None,
            help="Minimum sale total to include (default: no minimum).",
        )
        parser.add_argument(
            "--include-voided", dest="include_voided",
            action="store_true", default=False,
            help="Include voided sales (default: excluded).",
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
        date_from = _parse_date(options.get("date_from"), "date_from")
        date_to = _parse_date(options.get("date_to"), "date_to")
        if date_from is not None and date_to is not None and date_to < date_from:
            raise CommandError(
                f"End date {date_to.isoformat()} is before start date "
                f"{date_from.isoformat()}."
            )
        try:
            text = export_search_sales_csv(
                salon,
                client_name=options.get("client_name"),
                date_from=date_from,
                date_to=date_to,
                min_total=options.get("min_total"),
                include_voided=bool(options.get("include_voided", False)),
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
