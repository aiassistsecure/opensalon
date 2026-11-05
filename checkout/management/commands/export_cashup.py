"""Export a salon's cashups as CSV or JSON.

Usage:
    python manage.py export_cashup --salon-id ID
        --start-date YYYY-MM-DD [--end-date YYYY-MM-DD]
        [--format json|csv] [--output PATH]

Thin wrapper around the existing
:func:`checkout.cashup_export.export_cashups_csv` and
:func:`checkout.cashup_export.export_cashups` services:
the salon is resolved by id, the dates are parsed to
``datetime.date`` objects, and both are passed to the service
verbatim -- its output is written unchanged, to ``--output``
when given and to stdout otherwise. For ``--format csv`` (the
default) the service's CSV text is written exactly as before;
for ``--format json`` the same dict rows from
:func:`checkout.cashup_export.export_cashups` are serialised
as JSON, so the two formats can never disagree -- one source
of truth. The service's ``date_to`` is optional, so
``--end-date`` is optional here too and defaults to a
single-day export exactly as the service defines it. This
command adds no export logic of its own.

Invalid input -- an unparseable date, a reversed range, or
an unknown format -- raises ``CommandError``. Dates mean whole local days in the
salon's timezone, inclusive at both ends, exactly as the
service defines them. Read-only. Core stays
provider-agnostic -- no payment-provider SDK, field, or
name appears here.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from checkout.cashup_export import export_cashups, export_cashups_csv
from saloncore.models import Salon

_FORMATS = ("json", "csv")


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
    help = "Export a salon's cashups as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose cashups to export.",
        )
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            required=True,
            help="First day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive; "
                 "default: the start date, a single-day export).",
        )
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the export to (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        start = _parse_date(options["start_date"], "start date")
        end = _parse_date(options["end_date"], "end date")
        if end is not None and end < start:
            raise CommandError(
                f"End date {end.isoformat()} is before start date "
                f"{start.isoformat()}."
            )
        try:
            if fmt == "json":
                rows = export_cashups(salon, start, end)
                text = json.dumps(rows, indent=2) + "\n"
            else:
                text = export_cashups_csv(salon, start, end)
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
